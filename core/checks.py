"""Deploy-time checks for the details the site is legally required to publish.

WHY THESE ARE CHECKS AND NOT COMMENTS
-------------------------------------
The previous build carried the same requirements as `{# TODO #}` comments
inside templates: "street / service address goes here once confirmed",
"<a href='mailto:...'> goes here once confirmed", "insert the agreed
retention period". Comments do not fail a build. The result was a site
that would have gone live publishing `+91 XXXXX XXXXX` as its phone
number on all fifteen pages, with a privacy policy promising a contact
route that did not exist.

Django's check framework is the right place for this because it runs on
`manage.py check --deploy`, on `migrate`, and on `runserver` start, so a
missing legal detail surfaces before traffic does rather than after.

Everything here is scoped to `not DEBUG`. Local development must keep
working from a fresh clone with no .env, which is a property the settings
module deliberately preserves; a developer running `runserver` is not
publishing anything to a consumer.

THESE ARE NOT REGISTERED WITH deploy=True, AND THAT IS DELIBERATE
-----------------------------------------------------------------
`@register(deploy=True)` means "only run under `manage.py check
--deploy`". A typical build command is:

    collectstatic --noinput && migrate --noinput

It never calls `check --deploy`. So a deploy-only check here would have
been dead weight: it would pass silently on every deployment while the
site published a placeholder phone number, which is precisely the
false-assurance failure this module exists to prevent.

Registered plainly, they run as part of the standard check suite that
`migrate` and `runserver` invoke, so the build fails before the
new release goes live.

ESCAPE HATCH: Django already provides one, so none is invented here. To
ship with a known gap, name it explicitly in settings:

    SILENCED_SYSTEM_CHECKS = ["core.E004"]

That leaves a reviewable record of which duty was consciously deferred,
which a boolean bypass flag would not.

WHAT IS AN ERROR VERSUS A WARNING
---------------------------------
Errors block: `manage.py check` exits non-zero and Django refuses to
serve. Reserved for details whose absence either misleads a consumer
(a placeholder phone number) or breaches a specific statutory duty
(no grievance contact under DPDP s.13, no trader identity under the
Consumer Protection Act).

Warnings inform: printed but non-blocking. Used where the business may
legitimately have nothing to declare - a proprietor below the GST
threshold has no GSTIN, and publishing a fake one would be far worse
than publishing none.
"""

import os

from django.conf import settings
from django.core.checks import Error, register
from django.core.checks import Warning as CheckWarning

from core import context_processors as cp


def _value(name, pattern):
    """Re-run the context processor's own validation for one env var.

    Reads the environment rather than the rendered context because a check
    runs with no request. The patterns are imported from the context
    processor so there is exactly one definition of "valid" per field - if
    the check and the renderer disagreed, one of them would be wrong.
    """
    raw = (os.environ.get(name) or "").strip()
    return raw if pattern.fullmatch(raw) else ""


@register("compliance")
def check_publishable_business_identity(app_configs, **kwargs):
    """Refuse to run in production without the details the law requires."""
    if settings.DEBUG:
        return []

    problems = []

    # --- E001 phone -------------------------------------------------
    # The single worst failure mode on this site. Every page has a "Call
    # now" button, the mobile action bar is half phone, and an emergency
    # plumbing page tells a customer with water running to call rather
    # than message. Publishing the literal string "+91 XXXXX XXXXX"
    # breaks all of that silently.
    if not _value("SETU_PHONE_TEL", cp._TEL_RE):
        problems.append(
            Error(
                "SETU_PHONE_TEL is not set to a valid E.164 number, so every "
                "page would publish the placeholder "
                f"'{cp.DEFAULT_PHONE_TEL}' as a working phone number.",
                hint=(
                    "Set SETU_PHONE_TEL (e.g. +919812345678), plus "
                    "SETU_PHONE_DISPLAY and SETU_WA_NUMBER to match. All "
                    "three must describe the same line - "
                    "implementation_plan.md §8 NAP consistency."
                ),
                id="core.E001",
            )
        )
    if not _value("SETU_WA_NUMBER", cp._WA_RE):
        problems.append(
            Error(
                "SETU_WA_NUMBER is not set, so every wa.me link on the site "
                f"would point at the placeholder '{cp.DEFAULT_WA_NUMBER}'.",
                hint="Digits only, including country code, e.g. 919812345678.",
                id="core.E002",
            )
        )

    # --- E003 trader identity ---------------------------------------
    # Consumer Protection Act 2019 and the E-Commerce Rules 2020: a
    # consumer must be able to work out who they are dealing with and
    # where to reach them. A trading name over a city name identifies
    # nobody and is not a service of process address.
    if not _value("BUSINESS_PROPRIETOR", cp._NAME_RE):
        problems.append(
            Error(
                "BUSINESS_PROPRIETOR is not set. The site publishes a trading "
                "name ('Bajarangi Plumbing Services') with no identifiable "
                "person or registered entity behind it, so a customer has no "
                "one to hold to the terms of service.",
                hint=(
                    "Set BUSINESS_PROPRIETOR to the sole proprietor's full "
                    "legal name as it appears on the business's own records."
                ),
                id="core.E003",
            )
        )
    if not _value("BUSINESS_ADDRESS_STREET", cp._ADDR_RE):
        problems.append(
            Error(
                "BUSINESS_ADDRESS_STREET is not set. 'Bhubaneswar, Odisha, "
                "India' is not a trader address and cannot receive a legal "
                "notice or a consumer complaint.",
                hint=(
                    "Set BUSINESS_ADDRESS_STREET, and optionally "
                    "BUSINESS_ADDRESS_LOCALITY and BUSINESS_ADDRESS_PIN. "
                    "A residential address is acceptable for a sole "
                    "proprietor working from home; an unreachable one is not."
                ),
                id="core.E004",
            )
        )

    # --- E005 data-protection contact -------------------------------
    # DPDP Act 2023 s.5 (notice) and s.13 (grievance redressal), with the
    # DPDP Rules 2025 notified 13 November 2025. The forms collect name,
    # phone, address and a free-text problem description behind a consent
    # checkbox, which makes this business a Data Fiduciary. A Data
    # Principal must have a published route to exercise their rights, and
    # "message me on WhatsApp" is not durable evidence of one.
    if not (
        _value("GRIEVANCE_EMAIL", cp._EMAIL_RE) or _value("BUSINESS_EMAIL", cp._EMAIL_RE)
    ):
        problems.append(
            Error(
                "Neither GRIEVANCE_EMAIL nor BUSINESS_EMAIL is set. The site "
                "collects personal data under consent, which makes it a Data "
                "Fiduciary under the DPDP Act 2023, and s.13 requires a "
                "published contact for grievances and rights requests.",
                hint=(
                    "Set BUSINESS_EMAIL (and GRIEVANCE_EMAIL if different). "
                    "Rights requests need a written, timestamped channel; a "
                    "phone number alone cannot evidence a response."
                ),
                id="core.E005",
            )
        )

    return problems


@register("compliance")
def check_optional_business_disclosures(app_configs, **kwargs):
    """Non-blocking: flag disclosures that may legitimately not apply."""
    if settings.DEBUG:
        return []

    problems = []

    if not _value("BUSINESS_GSTIN", cp._GSTIN_RE):
        problems.append(
            CheckWarning(
                "BUSINESS_GSTIN is not set. If the business is GST-registered, "
                "the GSTIN should appear in the footer and on invoices; if it "
                "is below the registration threshold, this warning is correct "
                "and can be ignored.",
                hint=(
                    "Do not invent a GSTIN to silence this. A wrong GSTIN is a "
                    "false statement to a consumer and to the tax authority; a "
                    "missing one is merely incomplete."
                ),
                id="core.W001",
            )
        )

    # The alert path is how the owner learns a customer needs them. A lead
    # that saves but never alerts looks identical to success from the
    # browser, because main.js ignores the response body.
    if not settings.WHATSAPP_ACCESS_TOKEN and not settings.BREVO_API_KEY:
        problems.append(
            CheckWarning(
                "Neither WHATSAPP_ACCESS_TOKEN nor BREVO_API_KEY is set, so no "
                "owner alert can be delivered for a new lead. Leads will still "
                "be saved, but nobody will be told about them and the customer "
                "gets no indication of that.",
                id="core.W002",
            )
        )

    if not settings.OWNER_ALERT_EMAIL:
        problems.append(
            CheckWarning(
                "OWNER_ALERT_EMAIL is not set, so the email fallback cannot run "
                "when the WhatsApp Cloud API call fails.",
                id="core.W003",
            )
        )

    return problems


@register("security")
def check_debug_not_true_in_production(app_configs, **kwargs):
    """Warn or block if DEBUG is True in a production-like environment."""
    if not settings.DEBUG:
        return []

    problems = []

    # Heuristic for production: ALLOWED_HOSTS contains a public IP or domain.
    # By default, local environments use 127.0.0.1 or localhost.
    non_local_hosts = [
        host for host in settings.ALLOWED_HOSTS
        if host not in ("127.0.0.1", "localhost", "[::1]", "*")
    ]

    if non_local_hosts:
        problems.append(
            Error(
                "DEBUG is True, but ALLOWED_HOSTS contains non-local domains or IPs. "
                "Running with DEBUG=True in production is a severe security risk.",
                hint="Set DJANGO_DEBUG=False in your production .env or ensure ALLOWED_HOSTS does not contain public IPs in development.",
                id="core.E006",
            )
        )

    return problems
