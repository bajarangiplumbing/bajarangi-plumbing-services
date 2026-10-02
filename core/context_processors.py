"""Site-wide template context: contact identity, legal identity, policy dates.

`core/templates/base.html` documents the variables it expects and notes
that they should come from "a single context processor so there is one
source of truth per implementation_plan.md §8 NAP-consistency rule".
This is that context processor.

WHY THIS FILE GREW (compliance review, September 2026)
------------------------------------------------------
It used to expose four values: origin, phone display, phone tel, wa
number. That was enough to render a marketing site and not enough to
render a lawful one. Three separate bodies of law want an identifiable
trader behind the pages:

  - Consumer Protection Act 2019 read with the Consumer Protection
    (E-Commerce) Rules 2020: a consumer must be able to identify and
    reach the trader, and a grievance route must be published.
  - Digital Personal Data Protection Act 2023 s.5 and s.13, and the DPDP
    Rules 2025 notified on 13 November 2025: the notice given to a Data
    Principal must identify the Data Fiduciary and publish the contact
    details of the person who answers questions about the processing.
  - Legal Metrology / GST disclosure, if and when the business is
    registered.

So the legal identity now lives here, in one place, beside the phone
number, rather than being retyped into four policy pages that will drift
apart the first time anything changes.

EVERY LEGAL FIELD DEFAULTS TO EMPTY, ON PURPOSE
-----------------------------------------------
The previous version of this file claimed in its own docstring that
"the real number is +91 XXXXX XXXXX". It is not a number, it is a
placeholder with the digits typed as literal X characters, and it was
also the fallback - so a misconfigured deployment published an
unreachable phone number on all fifteen pages while the comment
asserted the opposite.

The lesson taken from that: an unset legal detail must be visibly
absent, never plausibly wrong. Templates guard on truthiness and simply
omit the line when a value is unset, and `core/checks.py` raises a
deploy-blocking error when DEBUG is off and a legally required value is
still missing. Inventing a street address or a GSTIN to fill a gap would
be worse than the gap: a wrong GSTIN is a false statement to a consumer,
whereas a missing one is merely incomplete.

Every value is validated against a strict pattern before it is returned
(security review L4). Three of these land inside base.html's
`application/ld+json` block and many are interpolated into `href`
attributes. Django's autoescape is an HTML escaper, which is the wrong
escaper for a JSON data block: a stray quote in SITE_URL would not
escape into script (raw-text elements do not decode entities) but it
would silently corrupt the structured data every page publishes.
Anything that does not match its pattern is replaced with the known-good
default rather than passed through.
"""

import datetime
import os
import re

# --- contact fallbacks ----------------------------------------------------
#
# These three stay as visible placeholders rather than a real number,
# because a wrong-but-plausible phone number is worse than an obviously
# unset one: a customer with a burst pipe dials it and reaches nobody,
# and nothing in the page tells them the site is misconfigured. The X
# characters are the signal. core/checks.py turns this into a hard error
# at deploy time (check `core.E001`).
DEFAULT_PHONE_DISPLAY = "+91 XXXXX XXXXX"
DEFAULT_PHONE_TEL = "+91XXXXXXXXXX"
DEFAULT_WA_NUMBER = "91XXXXXXXXXX"

# --- policy dates ---------------------------------------------------------
#
# One constant per document, edited by hand when that document's substance
# changes. Deliberately NOT `timezone.now()`: a policy page whose "last
# updated" date silently follows the clock tells the reader the terms were
# reviewed today when they were not, which is the sort of small untruth
# these pages exist to avoid. DPDP Rules 2025 and the Consumer Protection
# Act both make the *version* a consumer agreed to legally relevant.
POLICY_LAST_UPDATED = "8 September 2026"

# Bumped whenever the wording of the consent checkbox or the notice it
# links to changes in substance. Stored on every Lead and BookingRequest
# so that, years later, it is possible to prove exactly what a customer
# agreed to. DPDP s.6(1) requires consent to be informed and specific;
# that is unprovable without recording which text was shown.
CONSENT_NOTICE_VERSION = "2026-09-08"

# --- retention ------------------------------------------------------------
#
# DPDP Rules 2025 require a defined retention period and erasure once the
# purpose is served; the previous privacy page left this as an explicit
# TODO and no code ever deleted anything. These are the periods the policy
# text now publishes, and `manage.py purge_expired_leads` enforces them,
# so the three cannot drift apart.
#
# 18 months for a completed job is the pragmatic floor: the Consumer
# Protection Act 2019 allows a consumer two years from the cause of action
# to complain, and a workmanship dispute needs the job record to answer.
# Set RETENTION_ENQUIRY_DAYS / RETENTION_JOB_DAYS in the environment if the
# business decides on different periods, and the policy page follows
# automatically.
RETENTION_ENQUIRY_DAYS = int(os.environ.get("RETENTION_ENQUIRY_DAYS", "180"))
RETENTION_JOB_DAYS = int(os.environ.get("RETENTION_JOB_DAYS", "550"))

# An IP is kept only long enough for the abuse counters in
# core.views.submit_lead to mean anything (they look back one day), plus
# slack for investigating a burst. It is the least necessary field on the
# record, so it is erased first and separately.
RETENTION_IP_DAYS = int(os.environ.get("RETENTION_IP_DAYS", "30"))

# http(s) origin, optional port, optional path. No quotes, angle brackets,
# backslashes, whitespace or control characters can survive this.
_ORIGIN_RE = re.compile(
    r"^https?://[A-Za-z0-9.\-]+(?::\d{1,5})?(?:/[A-Za-z0-9._~\-/]*)?$"
)
# E.164-ish: a leading + and 8-15 digits.
_TEL_RE = re.compile(r"^\+\d{8,15}$")
# Digits only, country code included, as wa.me requires.
_WA_RE = re.compile(r"^\d{8,15}$")
# What a human-readable phone number may contain, and nothing else.
_DISPLAY_RE = re.compile(r"^[0-9+()\-\s]{8,24}$")
# Deliberately permissive but bounded: a person's or business's name in
# Latin or Odia script, no markup characters.
_NAME_RE = re.compile(r"^[^<>{}\"'\\\r\n\t]{2,120}$")
# One line of a postal address.
_ADDR_RE = re.compile(r"^[^<>{}\"'\\\r\n\t]{2,200}$")
# Indian PIN code.
_PIN_RE = re.compile(r"^\d{6}$")
# Conservative email shape. This value is rendered into a mailto: href, so
# what matters is that no quote, space or angle bracket gets through.
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{3,190}\.[A-Za-z]{2,24}$")
# GSTIN: 2-digit state code, 10-char PAN, entity digit, 'Z', checksum.
_GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}Z[A-Z\d]{1}$")


def _checked(raw, pattern, fallback):
    value = (raw or "").strip()
    return value if pattern.fullmatch(value) else fallback


def _env(name, pattern, fallback=""):
    return _checked(os.environ.get(name), pattern, fallback)


def business(request):
    """Contact identity, legal identity and policy metadata for every page."""
    # Trading name is hard-coded rather than environment-driven: it appears
    # in the logo SVG, the JSON-LD @id and the wordmark, so it is not
    # meaningfully configurable, and pretending otherwise would imply the
    # templates follow it when they do not.
    business_name = "Bajarangi Plumbing Services"

    street = _env("BUSINESS_ADDRESS_STREET", _ADDR_RE)
    locality = _env("BUSINESS_ADDRESS_LOCALITY", _ADDR_RE)
    city = _env("BUSINESS_ADDRESS_CITY", _ADDR_RE, "Bhubaneswar")
    state = _env("BUSINESS_ADDRESS_STATE", _ADDR_RE, "Odisha")
    pin = _env("BUSINESS_ADDRESS_PIN", _PIN_RE)

    # The address is only *complete* enough to publish as a trader address
    # when there is a street line. City and state alone identify nobody,
    # which is what the site published before.
    address_lines = [x for x in (street, locality) if x]
    address_tail = ", ".join(x for x in (city, state) if x)
    if pin:
        address_tail = f"{address_tail} {pin}".strip()
    if address_tail:
        address_lines.append(address_tail)
    address_lines.append("India")

    business_email = _env("BUSINESS_EMAIL", _EMAIL_RE)
    grievance_email = _env("GRIEVANCE_EMAIL", _EMAIL_RE) or business_email

    return {
        # --- origin -------------------------------------------------
        # Absolute origin with no trailing slash, e.g. https://example.com
        # Left empty by default: base.html then renders canonical and
        # og:url document-relative, which is valid but weaker.
        "site_url": _checked(
            os.environ.get("SITE_URL", "").rstrip("/"), _ORIGIN_RE, ""
        ),
        # --- contact ------------------------------------------------
        "phone_display": _env("SETU_PHONE_DISPLAY", _DISPLAY_RE, DEFAULT_PHONE_DISPLAY),
        "phone_tel": _env("SETU_PHONE_TEL", _TEL_RE, DEFAULT_PHONE_TEL),
        "wa_number": _env("SETU_WA_NUMBER", _WA_RE, DEFAULT_WA_NUMBER),
        # True only when a real number is configured. Templates use this to
        # decide whether to render a phone CTA at all, so a misconfigured
        # deployment shows no button rather than a dead one.
        "phone_is_real": _env("SETU_PHONE_TEL", _TEL_RE) != "",
        # --- legal identity ----------------------------------------
        "business_name": business_name,
        # Sole proprietor's name. Required to identify the trader: a
        # consumer cannot sue "Bajarangi Plumbing Services" if that is only
        # a trading style with no registered entity behind it.
        "business_proprietor": _env("BUSINESS_PROPRIETOR", _NAME_RE),
        "business_entity_type": _env(
            "BUSINESS_ENTITY_TYPE", _NAME_RE, "Sole proprietorship"
        ),
        "business_address_street": street,
        "business_address_locality": locality,
        "business_address_city": city,
        "business_address_state": state,
        "business_address_pin": pin,
        "business_address_lines": address_lines,
        "business_address_inline": ", ".join(address_lines),
        "business_address_is_complete": bool(street),
        "business_email": business_email,
        "business_gstin": _env("BUSINESS_GSTIN", _GSTIN_RE),
        # --- data protection contact --------------------------------
        # DPDP s.13(3) / Rule 13: publish a contact who answers questions
        # and handles grievances. For a one-person business this is the
        # proprietor, but it is a separate variable because the duty is
        # separate and may later be delegated.
        "grievance_name": _env("GRIEVANCE_CONTACT_NAME", _NAME_RE)
        or _env("BUSINESS_PROPRIETOR", _NAME_RE),
        "grievance_email": grievance_email,
        # --- policy metadata ---------------------------------------
        "policy_updated": POLICY_LAST_UPDATED,
        "consent_notice_version": CONSENT_NOTICE_VERSION,
        "retention_enquiry_months": max(1, round(RETENTION_ENQUIRY_DAYS / 30)),
        "retention_job_months": max(1, round(RETENTION_JOB_DAYS / 30)),
        "retention_ip_days": RETENTION_IP_DAYS,
        # Footer copyright. Computed, because a hard-coded year silently
        # goes stale and the footer already carried "© 2026" written by
        # hand. Asia/Kolkata is the business's own timezone, so the year
        # rolls over when it does for the owner.
        "current_year": datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        ).year,
    }
