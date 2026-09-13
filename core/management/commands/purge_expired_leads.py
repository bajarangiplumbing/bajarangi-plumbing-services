"""Erase personal data whose purpose has been served.

WHY THIS EXISTS
---------------
Before the September 2026 compliance review there was no deletion code
anywhere in the project. Not a management command, not a cron entry, not a
signal. Every Lead, every BookingRequest and every submission IP address
ever collected was kept indefinitely, while the privacy policy told
visitors their details were "removed" once no longer needed and left the
actual period as a `{% comment %}` TODO reading "Do not leave this vague
at launch."

Two duties are engaged. DPDP Act 2023 s.8(7) requires a Data Fiduciary to
erase personal data once the purpose is served and retention is no longer
required by law - the DPDP Rules 2025, notified 13 November 2025, put the
operational obligations on an 18-month runway ending 13 May 2027. And
s.5's notice duty means whatever period is published has to be the period
actually applied, which is only true if code enforces it.

The periods live in core/context_processors.py, are published by
/privacy/ from those same constants, and are enforced here. One source,
three consumers, so the policy text cannot drift away from the behaviour.

HOW TO RUN IT
-------------
    python manage.py purge_expired_leads --dry-run    # report only
    python manage.py purge_expired_leads              # actually erase

Schedule it daily. On a traditional server that is a crontab entry or systemd timer
running the same command; there is no in-process scheduler and adding one would be worse,
because a purge that only happens while a web worker is warm is a purge
that quietly stops happening.

WHAT IT DOES, IN ORDER OF INCREASING DESTRUCTIVENESS
----------------------------------------------------
1. Blanks `Lead.submission_ip` after RETENTION_IP_DAYS. The IP is the
   least necessary field on the record: it exists only so the per-day
   abuse counters in core.views.submit_lead mean something, and those look
   back exactly one day. Blanking is not deletion of the lead, so an
   enquiry stays answerable while the identifier goes early.
2. Deletes enquiries that never became work after RETENTION_ENQUIRY_DAYS.
3. Deletes records of completed work after RETENTION_JOB_DAYS.

Step 3 is deliberately the longest. The Consumer Protection Act 2019 gives
a consumer two years from the cause of action to complain, and answering a
workmanship dispute needs the job record to exist - so erasing it too
eagerly would defeat the customer's own remedy as well as the business's
defence. 550 days is the default compromise; override it in the
environment if the business decides otherwise.

WHAT IT DOES NOT TOUCH
----------------------
- `django_session`. That is `manage.py clearsessions`, which nothing
  currently schedules either. Run it alongside this command.
- `core_throttle_cache`. It holds SHA-256 hashes of IP addresses with
  short expiry times, but Django's DatabaseCache only deletes expired rows
  lazily, so they can outlive their logical expiry. The table sits outside
  the ORM by design, so it is cleaned by `--include-throttle` below rather
  than by a model query. Note that a hash of an IPv4 address is
  brute-forceable, which makes those rows pseudonymous personal data, not
  anonymous ones.
"""

import logging

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

from core.context_processors import (
    RETENTION_ENQUIRY_DAYS,
    RETENTION_IP_DAYS,
    RETENTION_JOB_DAYS,
    business,
)
from core.models import BookingRequest, Lead, LeadStatus

# Brevo's transactional endpoint - the same one core/notifications.py posts
# to for the lead-alert fallback. Named here rather than imported because
# the two callers need OPPOSITE error contracts; see _send_summary_email.
BREVO_ENDPOINT = "https://api.brevo.com/v3/smtp/email"

# Same logger name the lead pipeline uses, so a failed audit record lands in
# the same stream (and in Sentry, when a DSN is configured) as everything
# else that matters operationally.
logger = logging.getLogger("leads")

# An enquiry in one of these states never became work, so nothing depends
# on keeping it once the shorter clock runs out.
UNCONVERTED = [
    LeadStatus.NEW,
    LeadStatus.CONTACTED,
    LeadStatus.CANCELLED,
    LeadStatus.SPAM,
]

# These represent work that was agreed or carried out, so they follow the
# longer clock that leaves room for a consumer complaint.
CONVERTED = [
    LeadStatus.CONFIRMED,
    LeadStatus.ASSIGNED,
    LeadStatus.COMPLETED,
]


class Command(BaseCommand):
    help = "Erase leads, bookings and submission IPs whose retention period has passed."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be erased without changing anything.",
        )
        parser.add_argument(
            "--include-throttle",
            action="store_true",
            help=(
                "Also delete expired rows from the core_throttle_cache table. "
                "They hold hashed IPs and Django only culls them lazily."
            ),
        )

    def handle(self, *args, **options):
        dry = options["dry_run"]
        now = timezone.now()

        ip_cutoff = now - timezone.timedelta(days=RETENTION_IP_DAYS)
        enquiry_cutoff = now - timezone.timedelta(days=RETENTION_ENQUIRY_DAYS)
        job_cutoff = now - timezone.timedelta(days=RETENTION_JOB_DAYS)

        if dry:
            self.stdout.write(self.style.WARNING("DRY RUN - nothing will be changed.\n"))

        self.stdout.write(
            f"Cutoffs: IP {RETENTION_IP_DAYS}d, enquiry {RETENTION_ENQUIRY_DAYS}d, "
            f"job {RETENTION_JOB_DAYS}d\n"
        )

        # --- 1. submission IPs ---------------------------------------
        stale_ips = Lead.objects.filter(
            created_at__lt=ip_cutoff, submission_ip__isnull=False
        )
        ip_count = stale_ips.count()
        if ip_count and not dry:
            # .update() rather than a loop: one statement, no signals, and
            # it deliberately does not touch any other column.
            stale_ips.update(submission_ip=None)
        self._report("submission IPs blanked", ip_count, dry)

        # --- 2. unconverted enquiries --------------------------------
        old_enquiries = Lead.objects.filter(
            created_at__lt=enquiry_cutoff, status__in=UNCONVERTED
        )
        enquiry_count = old_enquiries.count()
        if enquiry_count and not dry:
            old_enquiries.delete()
        self._report("unconverted leads deleted", enquiry_count, dry)

        old_bookings = BookingRequest.objects.filter(
            created_at__lt=enquiry_cutoff, status__in=UNCONVERTED
        )
        booking_count = old_bookings.count()
        if booking_count and not dry:
            old_bookings.delete()
        self._report("unconverted bookings deleted", booking_count, dry)

        # --- 3. completed work ---------------------------------------
        old_jobs = Lead.objects.filter(created_at__lt=job_cutoff, status__in=CONVERTED)
        job_count = old_jobs.count()
        if job_count and not dry:
            old_jobs.delete()
        self._report("completed-work leads deleted", job_count, dry)

        old_job_bookings = BookingRequest.objects.filter(
            created_at__lt=job_cutoff, status__in=CONVERTED
        )
        job_booking_count = old_job_bookings.count()
        if job_booking_count and not dry:
            old_job_bookings.delete()
        self._report("completed-work bookings deleted", job_booking_count, dry)

        # --- 4. throttle counters, opt-in ----------------------------
        if options["include_throttle"]:
            self._purge_throttle(now, dry)

        self.stdout.write(self.style.SUCCESS("\nRetention pass complete."))
        self.stdout.write(
            "Reminder: run `manage.py clearsessions` too - nothing else prunes "
            "django_session.\n"
        )

        # --- 5. audit record -----------------------------------------
        # Sent last, after everything is committed, so the email can only
        # ever describe work that actually happened.
        #
        # Skipped on --dry-run: an audit email is a claim that records were
        # erased, and sending one when nothing was touched would make the
        # audit trail itself untrustworthy.
        if dry:
            self.stdout.write(
                self.style.WARNING("Dry run - no audit email sent.\n")
            )
            return

        self._send_summary_email(
            ran_at=now,
            ip_count=ip_count,
            enquiry_count=enquiry_count,
            booking_count=booking_count,
            job_count=job_count,
            job_booking_count=job_booking_count,
        )

    def _report(self, label, count, dry):
        verb = "would erase" if dry else "erased"
        style = self.style.WARNING if (dry and count) else self.style.SUCCESS
        self.stdout.write(style(f"  {verb} {count} {label}"))

    def _send_summary_email(
        self,
        ran_at,
        ip_count,
        enquiry_count,
        booking_count,
        job_count,
        job_booking_count,
    ):
        """Email one run summary to the business, as a compliance record.

        WHY THIS RAISES WHERE notifications.send_owner_email_alert SWALLOWS
        ------------------------------------------------------------------
        Both post to the same Brevo endpoint, but they exist for opposite
        reasons and therefore need opposite error contracts.

        A lead alert must never raise. The governing rule there is "never
        lose the lead": the row is already saved, the customer is already
        being served, and a failed alert is an inconvenience the owner can
        recover from by opening Admin. Swallowing is correct.

        This email IS the deliverable. It is the evidence that erasure
        actually ran on a given date - the thing that makes the retention
        period published on /privacy/ a fact rather than an intention. An
        audit record that fails silently is worse than none, because it
        leaves you believing a record exists when it does not. That is the
        same false-assurance failure the compliance review was opened to
        remove, so this one fails loudly: CommandError exits non-zero and
        the scheduled job supervisor marks the run as failed.

        The Brevo call is written here rather than imported from
        core/notifications.py deliberately. Sharing one helper would put a
        raising code path one careless edit away from the lead-alert flow,
        where raising would break the "never lose the lead" guarantee. The
        duplication is a few lines of HTTP shape; the coupling would be a
        latent bug. BREVO_ENDPOINT is named at module level so the URL
        itself is not repeated as a literal.
        """
        recipient = business(None)["business_email"]

        # Pre-flight, so a misconfiguration produces an actionable message
        # rather than a bare 401 from Brevo.
        missing = []
        if not settings.BREVO_API_KEY:
            missing.append("BREVO_API_KEY")
        if not settings.ALERT_FROM_EMAIL:
            missing.append("ALERT_FROM_EMAIL")
        if not recipient:
            missing.append("BUSINESS_EMAIL")
        if missing:
            message = (
                "Retention pass COMPLETED, but the audit email could not be "
                f"sent: {', '.join(missing)} not configured. The deletions "
                "above did happen - see this run's output for the counts - "
                "but no compliance record was delivered."
            )
            logger.error(message)
            raise CommandError(message)

        local = timezone.localtime(ran_at)
        stamp = local.strftime("%d %B %Y at %H:%M %Z")

        total = ip_count + enquiry_count + booking_count + job_count + job_booking_count
        headline = (
            "nothing to erase" if total == 0 else f"{total} record(s) erased"
        )

        rows = [
            ("Submission IP addresses cleared", ip_count),
            ("Unconverted enquiries deleted (leads)", enquiry_count),
            ("Unconverted enquiries deleted (bookings)", booking_count),
            ("Completed-job records deleted (leads)", job_count),
            ("Completed-job records deleted (bookings)", job_booking_count),
        ]
        rows_html = "".join(
            f"<tr><td style='padding:4px 12px 4px 0'>{label}</td>"
            f"<td style='padding:4px 0'><b>{count}</b></td></tr>"
            for label, count in rows
        )

        html = (
            f"<p>Data retention pass ran on <b>{stamp}</b> &mdash; {headline}.</p>"
            f"<table>{rows_html}</table>"
            f"<p style='color:#555;font-size:13px'>Retention periods applied: "
            f"IP addresses {RETENTION_IP_DAYS} days, unconverted enquiries "
            f"{RETENTION_ENQUIRY_DAYS} days, completed-job records "
            f"{RETENTION_JOB_DAYS} days.</p>"
            "<p style='color:#555;font-size:13px'>Automatic message from the "
            "website's scheduled retention job. Keep it as the record that "
            "erasure ran on this date.</p>"
        )

        try:
            resp = requests.post(
                BREVO_ENDPOINT,
                # Built inline so the API key is never bound to a frame
                # local, matching core/notifications.py (security review H1).
                headers={
                    "api-key": settings.BREVO_API_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "sender": {
                        "name": "Bajarangi Plumbing Services Website",
                        "email": settings.ALERT_FROM_EMAIL,
                    },
                    "to": [{"email": recipient}],
                    "subject": f"[Retention] {stamp} - {headline}",
                    "htmlContent": html,
                },
                timeout=8,
            )
            resp.raise_for_status()
        except Exception as exc:
            # Deliberately not swallowed - see the docstring.
            message = (
                "Retention pass COMPLETED, but the audit email FAILED to send "
                f"via Brevo: {exc}. The deletions above did happen; no "
                "compliance record was delivered for this run."
            )
            logger.exception(message)
            raise CommandError(message) from exc

        self.stdout.write(
            self.style.SUCCESS(f"Audit email sent to {recipient} - {headline}.\n")
        )

    def _purge_throttle(self, now, dry):
        """Delete expired rows from the DatabaseCache table.

        Raw SQL because this table has no model - it is created by
        core/migrations/0002 via `createcachetable` and is intentionally
        invisible to the ORM and to Admin. The table name matches
        settings.CACHES["throttle"]["LOCATION"].
        """
        table = "core_throttle_cache"
        with connection.cursor() as cursor:
            # `table` is a module-level constant, never user input, and the
            # timestamp is a bound parameter - so the f-string here is not an
            # injection surface. Django offers no ORM route to this table by
            # design (see the module docstring).
            cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE expires < %s", [now])
            count = cursor.fetchone()[0]
            if count and not dry:
                cursor.execute(f"DELETE FROM {table} WHERE expires < %s", [now])
        self._report(f"expired rows in {table}", count, dry)
