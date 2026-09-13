"""Owner alerts - backend_plan.md §8.

Two channels, in a deliberate order. WhatsApp is primary, because §1's
whole point is that the alert lands in Bajarangi's actual WhatsApp
without the customer having to tap anything. Email fires only when the
WhatsApp call fails, which is what makes `email_alert_status` in Django
Admin double as a "something went wrong" flag rather than a second
notification to check on every lead.

Both functions swallow every exception on purpose. By the time either is
called the lead row is already committed (§7.1), so a failed alert must
degrade to a recorded status and a log line - never to an error the
customer sees, and never to a lost lead.

The WhatsApp call is Path A: straight at Meta's Graph API, no BSP, no
platform fee. It needs the one-time console setup in §9 - a connected
number, a system-user token, and the approved `new_lead_alert` Utility
template, since Meta does not allow a free-form business-initiated
message (§4).

Three changes from the plan's §8 code, all from the security review:

  H1  The bearer token is never bound to a named local. Sentry captures
      frame locals, and this is the frame that raises, so a `headers`
      local containing "Bearer <token>" is a credential handed to a third
      party on every failure. settings.py also turns local capture off;
      this is the second lock on the same door. Same reasoning for not
      holding the lead's personal data in a local any longer than needed.

  M1  Every lead value interpolated into the email is HTML-escaped. The
      customer controls `customer_name` and `message`, and the email they
      land in is one the owner trusts and clicks links from.

  F1  Whitespace is collapsed before the message goes to Meta. The API
      rejects template parameters containing newlines, tabs, or runs of
      four or more spaces - and `message` comes from a <textarea>, so any
      customer who pressed Enter would silently kill the primary alert
      channel and force every such lead down the fallback path.
"""

import html
import logging

import requests
from django.conf import settings

from core.models import AlertStatus

logger = logging.getLogger("leads")

# Meta rejects a template parameter that contains a newline, a tab, or
# four or more consecutive spaces. Sending one costs the whole alert.
_MAX_TEMPLATE_PARAM_CHARS = 200


def _template_param(value):
    """Collapse a lead field into something Meta will accept (F1).

    str.split() with no argument splits on arbitrary whitespace runs and
    drops empties, so this flattens newlines, tabs and repeated spaces in
    one step. Truncation happens after the collapse, so the 200-character
    budget is spent on content rather than on discarded whitespace.
    """
    collapsed = " ".join((value or "").split())
    return collapsed[:_MAX_TEMPLATE_PARAM_CHARS]


def send_owner_whatsapp_alert(lead):
    """
    Sends the pre-approved 'new_lead_alert' Utility template to Setu
    Plumbing's own WhatsApp number via Meta's Cloud API, direct (Path A).
    Returns True on success, False on any failure (caller falls back to email).
    """
    url = (
        f"https://graph.facebook.com/v20.0/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": settings.OWNER_WHATSAPP_NUMBER,  # e.g. "91XXXXXXXXXX", no '+'
        "type": "template",
        "template": {
            "name": "new_lead_alert",  # the Utility template you create
            "language": {"code": "en"},  # or "en_US" per Meta's console
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": _template_param(lead.customer_name)},
                        {"type": "text", "text": _template_param(lead.locality)},
                        {
                            "type": "text",
                            "text": _template_param(lead.service_label)
                            or "Not specified",
                        },
                        {"type": "text", "text": _template_param(lead.message)},
                    ],
                }
            ],
        },
    }
    try:
        resp = requests.post(
            url,
            # Built inline, not assigned (H1): nothing in this frame's
            # locals may hold the access token, because this is the frame
            # an error reporter would snapshot.
            headers={
                "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()
        lead.whatsapp_message_id = data.get("messages", [{}])[0].get("id", "")
        lead.whatsapp_alert_status = AlertStatus.SENT
        lead.save(update_fields=["whatsapp_message_id", "whatsapp_alert_status"])
        return True
    except Exception:
        logger.exception(
            "WhatsApp Cloud API alert failed (lead is still saved in DB; "
            "falling back to email)."
        )
        lead.whatsapp_alert_status = AlertStatus.FAILED
        lead.save(update_fields=["whatsapp_alert_status"])
        return False


def _alert_email_html(lead):
    """The fallback email's body, with every lead value escaped (M1).

    `customer_name` and `message` are whatever the customer typed. Without
    escaping, a lead whose "issue" reads
    `<a href="https://evil.example/">Open in Admin</a>` renders as a
    working link inside an alert the owner trusts, beside the genuine
    Call / WhatsApp / Admin links - and an <img> would confirm he read it.

    `phone` is already reduced to ten digits by LeadForm.clean_phone, so
    the tel: and wa.me hrefs cannot be broken out of; it is escaped anyway
    rather than relying on validation elsewhere staying correct.
    """
    name = html.escape(lead.customer_name or "")
    phone = html.escape(lead.phone or "")
    locality = html.escape(lead.locality or "")
    service = html.escape(lead.service_label or "")
    message = html.escape(lead.message or "")
    # Built from the object's own _meta rather than a hard-coded
    # "core/lead" path. The hard-coded version was a real defect: a
    # BookingRequest was passed in wearing a MockLead wrapper, so its
    # primary key produced /admin/core/lead/<pk>/change/ - a link to an
    # unrelated Lead, i.e. a DIFFERENT customer's record, inside the alert
    # the owner trusts. Derived this way it cannot be wrong for either
    # model, and it cannot go stale if a model is ever renamed.
    admin_url = html.escape(
        f"{settings.SITE_URL}/admin/{lead._meta.app_label}"
        f"/{lead._meta.model_name}/{lead.pk}/change/",
        quote=True,
    )
    return f"""
                  <p><b>{name}</b> &mdash; {phone}</p>
                  <p>Area: {locality}<br>Service: {service}</p>
                  <p>Issue: {message}</p>
                  <p><a href="tel:+91{phone}">Call now</a> &middot;
                     <a href="https://wa.me/91{phone}">WhatsApp customer</a> &middot;
                     <a href="{admin_url}">Open in Admin</a></p>
                """


def send_owner_email_alert(lead):
    """Free Brevo email - automatic fallback if the WhatsApp API call fails."""
    try:
        resp = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            # Inline for the same reason as the WhatsApp call above (H1).
            headers={
                "api-key": settings.BREVO_API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "sender": {
                    "name": "Bajarangi Plumbing Services Website",
                    "email": settings.ALERT_FROM_EMAIL,
                },
                "to": [
                    {
                        "email": settings.OWNER_ALERT_EMAIL,
                        "name": "Bajarangi Plumbing Services",
                    }
                ],
                # Collapsed, not escaped: this is a header value, so what
                # matters is that it carries no newlines.
                "subject": (
                    "[WhatsApp alert failed] New lead: "
                    f"{_template_param(lead.customer_name)} "
                    f"({_template_param(lead.locality)})"
                ),
                "htmlContent": _alert_email_html(lead),
            },
            timeout=8,
        )
        resp.raise_for_status()
        lead.email_alert_status = AlertStatus.SENT
    except Exception:
        logger.exception("Email fallback also failed - check Django Admin manually.")
        lead.email_alert_status = AlertStatus.FAILED
    lead.save(update_fields=["email_alert_status"])
