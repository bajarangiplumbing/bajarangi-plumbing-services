"""Security controls for the lead-capture backend.

Everything here closes a finding from the security review of the code in
backend_plan.md §7.1, §8 and §11. The plan does not describe this module;
it exists because implementing the plan literally left five exploitable
gaps. Each control below names the finding it closes.

Deliberately no new third-party dependency: `django-axes`, `django-csp`
and `django-ipware` would each solve one piece of this, and all three
would be more code to audit than the ~80 lines they replace.

Contents:
  client_ip()                     H2 - the real caller, not the proxy
  rate_limit()                    H2/H4 - one durable counter, two users
  HardenedExceptionReporterFilter M4 - stop the debug page printing
                                  credentials Django does not recognise
  SecurityHeadersMiddleware       L3 - CSP and Permissions-Policy
  AdminLoginRateLimitMiddleware   H4 - lockout on /admin/login/
  the two login signal receivers  H4 - what feeds that lockout
"""

from __future__ import annotations

import hashlib
import ipaddress
import re

from django.conf import settings
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.core.cache import InvalidCacheBackendError, caches
from django.dispatch import receiver
from django.http import HttpResponse
from django.urls import NoReverseMatch, reverse
from django.views.debug import SafeExceptionReporterFilter

# Security counters live in their own cache alias so that CACHES["default"]
# can stay exactly as backend_plan.md §11 specifies it. The default is
# LocMemCache: per-process and wiped on every restart, which is fine for
# ordinary caching and useless for a throttle - a second gunicorn worker
# gets its own empty counter, and a deploy resets everyone's. The
# "throttle" alias is database-backed so both controls below survive
# restarts and are shared across workers.
THROTTLE_CACHE_ALIAS = "throttle"


def _counter_store():
    """The durable cache if configured, otherwise whatever is available.

    Falling back rather than raising is deliberate: a misconfigured cache
    alias must not take the lead form offline. It degrades the throttle,
    which is the lesser harm - §1's rule is that a lead is never lost.
    """
    try:
        return caches[THROTTLE_CACHE_ALIAS]
    except InvalidCacheBackendError:
        return caches["default"]


# --------------------------------------------------------------- client IP
#
# H2. `request.META["REMOTE_ADDR"]` is whoever opened the TCP connection.
# With Cloudflare and/or a reverse proxy in front of Django that is a proxy, not the
# visitor, so a REMOTE_ADDR-keyed throttle either lumps every visitor into
# one bucket (throttling real customers) or tracks edge IPs (throttling
# nobody).
#
# The correct source depends on the deployment, and guessing is worse than
# not guessing: any header a client can set is spoofable, so trusting
# X-Forwarded-For blindly hands an attacker an unlimited supply of
# identities and makes the throttle purely decorative. So this is
# configuration, and the default is the safe one.
#
#   CLIENT_IP_HEADER=""                  -> REMOTE_ADDR (default, safe)
#   CLIENT_IP_HEADER="CF-Connecting-IP"  -> Cloudflare proxying (orange
#                                           cloud). Single value, set by
#                                           the edge, not forwardable.
#   CLIENT_IP_HEADER="X-Forwarded-For"   -> needs CLIENT_IP_TRUSTED_PROXIES
#
# X-Forwarded-For is a left-to-right append trail: "client, edge1, edge2".
# Only the entries your own infrastructure appended can be trusted, so the
# client is the Nth from the *right* where N is the number of trusted
# proxies in front of the app. Nginx alone is 1; Cloudflare in front of
# Nginx is 2. Setting N too high reads a spoofed value, so it is explicit
# rather than sniffed.


def _meta_key(header_name):
    return "HTTP_" + header_name.upper().replace("-", "_")


def _coerce_ip(candidate):
    """Return a normalised IP string, or None if it is not an address."""
    value = (candidate or "").strip()
    if not value:
        return None
    # Some proxies append a port, and IPv6 literals arrive bracketed.
    if value.startswith("["):
        value = value[1:].partition("]")[0]
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass
    host, sep, _port = value.rpartition(":")
    if sep and host:
        try:
            return str(ipaddress.ip_address(host.strip("[]")))
        except ValueError:
            return None
    return None


def _from_forwarding_header(raw):
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    try:
        depth = int(getattr(settings, "CLIENT_IP_TRUSTED_PROXIES", 1) or 1)
    except (TypeError, ValueError):
        depth = 1
    depth = max(1, min(depth, len(parts)))
    return parts[-depth]


def client_ip(request):
    """The caller's IP as a validated string, or None if there isn't one.

    Never returns a non-address. The reviewed code stored the literal
    string "unknown" into `Lead.submission_ip`, which is a Postgres `inet`
    column - that save raises, and it raises *after* the notification
    decision, i.e. on the one path that must not fail. None is storable
    (the column is nullable); "unknown" is not.
    """
    header = getattr(settings, "CLIENT_IP_HEADER", "") or ""
    if header:
        raw = request.META.get(_meta_key(header), "")
        if raw:
            found = _coerce_ip(_from_forwarding_header(raw))
            if found:
                return found
    return _coerce_ip(request.META.get("REMOTE_ADDR", ""))


# ------------------------------------------------------------- rate limits


def _counter_key(bucket, identity):
    # The identity is hashed rather than stored: these keys land in a
    # database table, and a bucket keyed on a phone number would put
    # customer PII into a cache table with a different retention story
    # from the Lead row it came from.
    digest = hashlib.sha256(f"{bucket}\x00{identity}".encode()).hexdigest()
    return f"rl:{bucket}:{digest[:32]}"


def rate_limit(bucket, identity, limit, window):
    """Count one hit. Returns (allowed, retry_after_seconds).

    A fixed-window counter whose window extends on each hit, which is what
    the reviewed code did and is the stricter reading. Read-then-write is
    not atomic, so a burst of exactly-simultaneous requests can slip one or
    two past the limit; that is acceptable here because the authoritative
    cap on the expensive action is the database count in
    `core.views.submit_lead`, not this counter. This one exists to reject
    the cheap floods before they reach validation.
    """
    if not identity:
        identity = "anonymous"
    key = _counter_key(bucket, identity)
    store = _counter_store()
    count = store.get(key) or 0
    if count >= limit:
        return False, window
    store.set(key, count + 1, timeout=window)
    return True, 0


def rate_limit_peek(bucket, identity, limit):
    """Is this identity already over the limit? Does not count a hit."""
    if not identity:
        identity = "anonymous"
    return (_counter_store().get(_counter_key(bucket, identity)) or 0) >= limit


def rate_limit_clear(bucket, identity):
    if not identity:
        identity = "anonymous"
    _counter_store().delete(_counter_key(bucket, identity))


# --------------------------------------------- debug page setting masking
#
# M4. Django's own filter masks any setting whose name matches
# API|AUTH|TOKEN|KEY|SECRET|PASS|SIGNATURE|HTTP_COOKIE (verified in
# django/views/debug.py). That covers WHATSAPP_ACCESS_TOKEN and
# BREVO_API_KEY by luck of naming, and misses SENTRY_DSN outright, plus
# OWNER_WHATSAPP_NUMBER / OWNER_ALERT_EMAIL / ALERT_FROM_EMAIL, which are
# the owner's personal contact details. Anything reachable on a traceback
# page with DEBUG on is worth masking, since the whole point of that page
# is to be read by whoever triggered the error.


class HardenedExceptionReporterFilter(SafeExceptionReporterFilter):
    """Django's filter, plus this project's own credential names."""

    hidden_settings = re.compile(
        "API|AUTH|TOKEN|KEY|SECRET|PASS|SIGNATURE|HTTP_COOKIE"
        "|DSN|SENTRY|WHATSAPP|BREVO|OWNER|ALERT|DATABASE|EMAIL",
        flags=re.IGNORECASE,
    )


# ------------------------------------------------------- response headers


def _build_csp():
    """The site's Content-Security-Policy.

    L3. Unusually cheap to lock down here: there is no third-party
    JavaScript, no CDN, no analytics and no inline <script> that executes -
    base.html's only inline block is `application/ld+json`, which is a data
    block, not an executable script, so `script-src 'self'` does not affect
    it.

    'unsafe-inline' is required in style-src and nowhere else: several
    templates carry `style="..."` attributes (the coloured channel icons on
    the contact page, for instance). Inline *style attributes* are governed
    by style-src; the `.style.transform` writes main.js makes are CSSOM
    calls and are not.
    """
    directives = [
        "default-src 'self'",
        "base-uri 'none'",
        "object-src 'none'",
        "frame-ancestors 'none'",
        "form-action 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "manifest-src 'self'",
    ]
    if not settings.DEBUG:
        directives.append("upgrade-insecure-requests")
    return "; ".join(directives)


class SecurityHeadersMiddleware:
    """Adds CSP and Permissions-Policy to public responses.

    Django Admin is exempt. Its templates contain inline <script> blocks,
    so a strict script-src would break the console the owner reads leads
    in - and breaking that is a worse outcome than the marginal CSP benefit
    on a staff-only, authenticated, is_staff-gated surface that already has
    X-Frame-Options DENY and SameSite cookies. Revisit if the admin is ever
    exposed more widely.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.csp = _build_csp()
        self.permissions_policy = (
            "geolocation=(), camera=(), microphone=(), payment=(), usb=()"
        )

    def __call__(self, request):
        response = self.get_response(request)
        if not request.path.startswith("/admin/"):
            response.setdefault("Content-Security-Policy", self.csp)
            response.setdefault("Permissions-Policy", self.permissions_policy)
        return response


# ------------------------------------------------------ admin login lockout
#
# H4. /admin/ is internet-facing with no lockout, no 2FA and no IP
# restriction. Two problems, not one: unlimited online password guessing,
# and the fact that each guess costs a full PBKDF2 verification (Django 6
# defaults to ~1.2M iterations), which makes the login form the cheapest
# way to exhaust CPU on a single free-tier instance.
#
# The URL stays at /admin/ on purpose. Moving it is obscurity, not a
# control, and backend_plan.md §8's alert email hardcodes
# /admin/core/lead/<id>/change/ - so relocating it would silently break
# the one link the owner clicks from every fallback alert.

ADMIN_LOGIN_BUCKET = "admin-login"

# Used by core.views.submit_lead. Named here so the two buckets that share
# this counter store are declared in one place.
LEAD_IP_BUCKET = "lead-ip"


def _admin_login_limit():
    return int(getattr(settings, "ADMIN_LOGIN_MAX_FAILURES", 10))


def _admin_login_window():
    return int(getattr(settings, "ADMIN_LOGIN_LOCKOUT_SECONDS", 900))


@receiver(user_login_failed)
def _count_failed_login(sender, credentials=None, request=None, **kwargs):
    """Count a failed attempt against the caller's IP.

    Keyed on IP, not username: keying on the username lets anyone lock the
    owner out of his own admin by guessing at his account on purpose.
    """
    if request is None:
        return
    rate_limit(
        ADMIN_LOGIN_BUCKET,
        client_ip(request) or "unresolved",
        _admin_login_limit(),
        _admin_login_window(),
    )


@receiver(user_logged_in)
def _clear_failed_logins(sender, request=None, user=None, **kwargs):
    """A correct password clears the counter for that IP."""
    if request is None:
        return
    rate_limit_clear(ADMIN_LOGIN_BUCKET, client_ip(request) or "unresolved")


class AdminLoginRateLimitMiddleware:
    """Rejects admin login POSTs from an IP that is over the failure limit.

    Runs before the view, so a locked-out attempt never reaches the
    password hasher - which is the point, since the hashing is the
    expensive part.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self._login_path = None

    def _admin_login_path(self):
        if self._login_path is None:
            try:
                self._login_path = reverse("admin:login")
            except NoReverseMatch:
                self._login_path = ""
        return self._login_path

    def __call__(self, request):
        if request.method == "POST":
            path = self._admin_login_path()
            if path and request.path == path:
                identity = client_ip(request) or "unresolved"
                if rate_limit_peek(ADMIN_LOGIN_BUCKET, identity, _admin_login_limit()):
                    window = _admin_login_window()
                    return HttpResponse(
                        "Too many failed sign-in attempts. Try again later.",
                        status=429,
                        headers={"Retry-After": str(window)},
                        content_type="text/plain; charset=utf-8",
                    )
        return self.get_response(request)
