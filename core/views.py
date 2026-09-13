"""Views: the fifteen public pages, plus the lead-capture endpoint.

Every page in PRD_website_pages.md §1.2's sitemap is static content: the
templates carry their own copy, metadata and structured data, so
`PageView` has nothing to fetch and nothing to decide.

`submit_lead` is backend_plan.md §7.1, and it exists to serve §1's one
rule: a submitted lead must never depend on the customer's phone,
browser or WhatsApp app behaving correctly. Note the ordering inside it -
the row is saved *before* either notification is attempted, and neither
notification can fail the request. Once `lead.save()` returns, the lead
is durable whatever happens next.

`healthz` is backend_plan.md §10/§12: the endpoint UptimeRobot pings.

Four changes from §7.1's code, all from the security review:

  H2  The caller is identified with `core.security.client_ip()` instead of
      REMOTE_ADDR. Behind Cloudflare or a reverse proxy, REMOTE_ADDR is the proxy,
      which made the throttle either global (one bucket for every real
      visitor - §1 violated by the mitigation itself) or meaningless.
      That helper also guarantees a storable value: the old code wrote the
      literal string "unknown" into an `inet` column when REMOTE_ADDR was
      absent, which raises on save, after the point of no return.

  H2  The per-IP counter is now durable and shared (see settings' CACHES),
      and a second, authoritative cap is enforced against the database.
      The cache counter rejects cheap floods early; the database counts
      are what actually bound the number of billable WhatsApp sends an
      attacker can buy, because a cache can be reset by a restart and a
      database row cannot.

  M2  `dedupe_key` covers locality as well as phone and message, and the
      window is configurable. Dedupe alone was never replay protection -
      changing one character of the message defeats it instantly - so the
      per-phone daily cap is what actually limits a replayed submission.

Still deferred (backend_plan.md §13): no server-rendered POST fallback
for the form, so implementation_plan.md §12's "every essential page works
without JavaScript" is still met only by the templates' <noscript> call /
WhatsApp links, not by this endpoint. The frontend `fetch()` in §7.2 that
would call this endpoint has not been added either.
"""

import datetime
import hashlib
import logging
from typing import ClassVar

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from core.forms import SLOT_START_HOUR, BookingForm, LeadForm
from core.models import Lead, LeadSource
from core.notifications import send_owner_email_alert, send_owner_whatsapp_alert
from core.security import LEAD_IP_BUCKET, client_ip, rate_limit

logger = logging.getLogger("leads")


class PageView(TemplateView):
    """Render a static content page.

    Touches no database and takes no user input. `template_name` is
    supplied per route in `core/urls.py`, which keeps the whole sitemap
    readable in one place.
    """

    # Read-only pages: these never accept a POST.
    http_method_names: ClassVar[list[str]] = ["get", "head", "options"]


class GoneServiceView(TemplateView):
    """Return an honest 410 page for retired public service URLs."""

    template_name = "pages/services/gone.html"
    http_method_names: ClassVar[list[str]] = ["get", "head", "options"]

    def render_to_response(self, context, **response_kwargs):
        response_kwargs.setdefault("status", 410)
        return super().render_to_response(context, **response_kwargs)


def _too_many(message, retry_after):
    response = JsonResponse({"ok": False, "error": message}, status=429)
    response["Retry-After"] = str(int(retry_after))
    return response


@require_POST
def submit_lead(request):
    """Accept one lead, save it, then alert the owner.

    CSRF-protected by the project's CsrfViewMiddleware (§10), so callers
    must send the token - §7.2's `fetch()` sends it as X-CSRFToken.
    """
    ip = client_ip(request)
    identity = ip or "unresolved"

    # Cheap gate first: rejects a flood before it reaches validation or
    # the database. Durable and shared across workers, unlike the
    # in-memory counter this replaces.
    allowed, retry_after = rate_limit(
        LEAD_IP_BUCKET,
        identity,
        settings.LEAD_MAX_PER_IP,
        settings.LEAD_RATE_WINDOW_SECONDS,
    )
    if not allowed:
        return _too_many("Too many requests. Please try again later.", retry_after)

    data = request.POST.copy()
    if "customer_name" not in data and "name" in data:
        data["customer_name"] = data["name"]
    if "locality" not in data and "area" in data:
        data["locality"] = data["area"]
    if "service_label" not in data and "service" in data:
        data["service_label"] = data["service"]
    if "message" not in data and "issue" in data:
        data["message"] = data["issue"]

    form = LeadForm(data)
    if not form.is_valid():
        return JsonResponse({"ok": False, "errors": form.errors}, status=400)

    consent = request.POST.get("consent") in ("1", "true", "on", "yes")
    if not consent:
        return JsonResponse({"ok": False, "error": "Consent is required."}, status=400)

    lead = form.save(commit=False)
    lead.source = LeadSource.WEBSITE_FORM
    lead.consent_given = True
    lead.consent_at = timezone.now()
    # Which wording the customer actually saw. Truncated rather than
    # rejected: a mismatched or absent version must never cost a lead, and
    # an unexpected value is itself the useful signal.
    lead.consent_notice_version = (
        request.POST.get("consent_notice_version") or ""
    ).strip()[:32]
    # None rather than a placeholder string: the column is `inet` and
    # nullable, and an unparseable value would raise here (H2).
    lead.submission_ip = ip

    # Locality joins the key (M2) so two genuinely different jobs at
    # different addresses from one phone are not collapsed into one.
    dedupe_raw = (
        f"{lead.phone}:{lead.locality.strip().lower()}:{lead.message.strip().lower()}"
    )
    lead.dedupe_key = hashlib.sha256(dedupe_raw.encode()).hexdigest()
    dedupe_window = timezone.timedelta(minutes=settings.LEAD_DEDUPE_WINDOW_MINUTES)
    recent_dup = Lead.objects.filter(
        dedupe_key=lead.dedupe_key,
        created_at__gte=timezone.now() - dedupe_window,
    ).exists()
    if recent_dup:
        return JsonResponse({"ok": True, "duplicate": True})

    # Authoritative caps, counted in the database so they survive a
    # restart, a deploy, and a cache flush (H2/M2). Each accepted lead
    # costs a real WhatsApp Utility send, so these bound spend as much as
    # they bound rows.
    #
    # A genuine customer who trips these has not lost anything: the
    # browser's own wa.me handoff is untouched and still delivers their
    # message. That is what makes it safe to refuse here at all.
    day_ago = timezone.now() - timezone.timedelta(days=1)
    if ip and (
        Lead.objects.filter(submission_ip=ip, created_at__gte=day_ago).count()
        >= settings.LEAD_MAX_PER_IP_PER_DAY
    ):
        # Neither the IP nor the phone is logged: both are personal data,
        # and a warning becomes a Sentry breadcrumb. Accepted leads carry
        # submission_ip in the row itself if an abuse case needs tracing.
        logger.warning("Lead rejected: per-IP daily cap reached.")
        return _too_many("Daily limit reached. Please call or WhatsApp instead.", 3600)

    if (
        Lead.objects.filter(phone=lead.phone, created_at__gte=day_ago).count()
        >= settings.LEAD_MAX_PER_PHONE_PER_DAY
    ):
        logger.warning("Lead rejected: per-phone daily cap reached.")
        return _too_many("Daily limit reached. Please call or WhatsApp instead.", 3600)

    # The lead is durable from this line onward, regardless of anything
    # that happens with the notifications below.
    lead.save()

    # WhatsApp is the primary channel; email is the automatic fallback.
    wa_ok = send_owner_whatsapp_alert(lead)
    if not wa_ok:
        send_owner_email_alert(lead)

    return JsonResponse({"ok": True, "lead_id": lead.id})


def healthz(request):
    return JsonResponse({"ok": True})


@require_POST
def submit_booking(request):
    ip = client_ip(request)
    identity = ip or "unresolved"

    allowed, retry_after = rate_limit(
        LEAD_IP_BUCKET,
        identity,
        settings.LEAD_MAX_PER_IP,
        settings.LEAD_RATE_WINDOW_SECONDS,
    )
    if not allowed:
        return _too_many("Too many requests. Please try again later.", retry_after)

    data = request.POST.copy()
    if "customer_name" not in data and "name" in data:
        data["customer_name"] = data["name"]
    if "locality" not in data and "area" in data:
        data["locality"] = data["area"]
        data["address"] = data["area"]
    if "service_label" not in data and "service" in data:
        data["service_label"] = data["service"]
    if "preferred_time_slot" not in data and "preferred_time" in data:
        data["preferred_time_slot"] = data["preferred_time"]

    # The previous version of this view concatenated the customer's email
    # address, preferred date and slot into `message` as free text, e.g.
    #     "Email: someone@example.com\nPreferred: 2026-09-12 Morning"
    # Three problems with that, all now fixed by giving each value a real
    # column on BookingRequest:
    #   1. The email was stored TWICE - once in its own column and once
    #      inside a text blob. An erasure or export routine keyed on
    #      columns silently misses the second copy, so "delete my data"
    #      would have left the address behind.
    #   2. `preferred_datetime` stayed NULL forever, so the typed column
    #      the schema already had was dead while the data sat in prose.
    #   3. The blob was then forwarded verbatim to Meta and to Brevo,
    #      widening what each processor received for no reason.

    form = BookingForm(data)
    if not form.is_valid():
        return JsonResponse({"ok": False, "errors": form.errors}, status=400)

    consent = data.get("consent") in ("1", "true", "on", "yes")
    if not consent:
        return JsonResponse({"ok": False, "error": "Consent is required."}, status=400)

    booking = form.save(commit=False)
    booking.source = LeadSource.WEBSITE_FORM
    booking.consent_given = True
    booking.consent_at = timezone.now()
    booking.consent_notice_version = (
        data.get("consent_notice_version") or ""
    ).strip()[:32]

    # Populate the typed datetime from the validated date plus the start
    # hour of the chosen slot, so the admin can sort and filter on it.
    # timezone.make_aware because USE_TZ is on and TIME_ZONE is
    # Asia/Kolkata - a naive datetime here would warn and be interpreted
    # as UTC, putting a morning slot at 02:30 local.
    if booking.preferred_date:
        hour = SLOT_START_HOUR.get(booking.preferred_time_slot, 8)
        booking.preferred_datetime = timezone.make_aware(
            datetime.datetime.combine(
                booking.preferred_date, datetime.time(hour=hour)
            )
        )

    booking.save()

    # No MockLead duck-type any more. BookingRequest now carries the three
    # alert-status fields itself, which fixes two defects the fake object
    # caused: its save() was a no-op, so every booking's delivery status
    # was silently discarded, and it passed a booking's primary key to a
    # notifier that built /admin/core/lead/<pk>/change/ - a link that
    # resolved to an unrelated Lead, i.e. a different customer's record,
    # inside the owner's own alert email.
    wa_ok = send_owner_whatsapp_alert(booking)
    if not wa_ok:
        send_owner_email_alert(booking)

    return JsonResponse({"ok": True, "booking_id": booking.id})
