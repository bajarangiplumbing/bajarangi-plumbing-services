"""Django settings for Bajarangi Plumbing Services.

Scope: the frontend in `core/templates` / `core/static`, plus the
lead-capture backend specified in backend_plan.md.

What is here:
  - template and static-file configuration
  - one context processor supplying the site-wide contact details, so
    there is a single source of truth for name/phone (§8 NAP rule)
  - environment-based secrets (§6 "Store credentials and API keys only
    in environment variables; never commit them")
  - HTTPS / secure-cookie settings, active whenever DEBUG is off (§6)
  - a configured PostgreSQL connection (§6 "PostgreSQL in production"),
    read from DATABASE_URL - see the DATABASES block below
  - Django Admin and its dependencies, which backend_plan.md §6, §8 and
    §10 all rely on as the staff console for leads
  - the locmem cache the §7.1 per-IP lead throttle counts in
  - WhatsApp Cloud API and Brevo credentials, read from the environment
    (backend_plan.md §11), consumed by core/notifications.py

What is NOT here, and is still deferred by backend_plan.md §13:
  - no Celery/Redis queue; §8's try/except + email fallback is the
    notification path at this volume
  - no customer-facing WhatsApp confirmation template
  - the `fetch()` call that posts the browser form to /api/lead/
    (backend_plan.md §7.2) is a frontend change and has not been made;
    the endpoint exists and is reachable, nothing calls it yet
"""

import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Reads BASE_DIR/.env if present. .env is gitignored; .env.example is the
# committed template.
load_dotenv(BASE_DIR / ".env")


def _bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _list(name, default=""):
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


DEBUG = _bool("DJANGO_DEBUG", False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "").strip()
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off. "
            "Copy .env.example to .env and fill it in."
        )
    # Ephemeral key for local development only. Never reused, never
    # written to disk, and unreachable when DEBUG is off.
    from django.core.management.utils import get_random_secret_key

    SECRET_KEY = get_random_secret_key()

ALLOWED_HOSTS = _list("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost")

# Error monitoring: backend_plan.md §10, and §12 step 7 - "Sentry -> free
# tier, one line in settings.py". A blank DSN disables it outright, which
# is the local default; the production environment supplies the real one.
#
# The three non-default options are a security fix, not tuning.
#
# send_default_pii=False keeps request bodies, headers and user identity
# off events. On its own that is NOT enough, which is the trap: it does
# not touch local variables, and include_local_variables defaults to
# True. core/notifications.py raises inside a frame whose locals hold the
# Authorization header - so with stock settings, every WhatsApp failure
# would ship a long-lived Meta access token, plus the customer's name,
# phone and message, to a third party. That failure path is also the one
# that fires most often. Hence include_local_variables=False, which is
# the actual control; the notifications module additionally avoids
# binding the token to a named local as defence in depth.
#
# max_request_body_size="never" is belt-and-braces on the same idea: the
# lead POST body *is* the customer's personal data.
SENTRY_DSN = os.environ.get("SENTRY_DSN", "").strip()
if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        send_default_pii=False,
        include_local_variables=False,
        max_request_body_size="never",
    )

INSTALLED_APPS = [
    # Admin, and the four contrib apps it cannot run without.
    # backend_plan.md needs it in three separate places: §6 requires
    # `whatsapp_alert_status` to be "visible and filterable in Django
    # Admin", §8's email fallback links to
    # /admin/core/lead/<id>/change/, and §10 restricts access with
    # "Django's built-in is_staff flag".
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.messages",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "django.contrib.sitemaps",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "django_otp.plugins.otp_static",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Serves STATIC_ROOT in production if no separate web server is used.
    # WhiteNoise's own docs
    # require it directly below SecurityMiddleware and above everything
    # else. backend_plan.md §11 names whitenoise as a dependency and
    # sets its storage backend below.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    # Adds CSP and Permissions-Policy on the way out (security review L3).
    # High in the list so it sees every response, including error pages.
    "core.security.SecurityHeadersMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    # Blocks admin login POSTs from an IP that is over the failure limit
    # (security review H4). Below AuthenticationMiddleware so `request.user`
    # exists, and before the admin view so a locked-out guess never reaches
    # the password hasher - the hashing is the expensive part being abused.
    "core.security.AdminLoginRateLimitMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "plumber_site.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # APP_DIRS finds core/templates/, which is where the frontend
        # lives per implementation_plan.md §6.
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                # Both are required by django.contrib.admin's templates
                # (checks admin.E402 / admin.E404). The public pages do
                # not read `user`, `perms` or `messages`.
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.business",
            ],
        },
    },
]

WSGI_APPLICATION = "plumber_site.wsgi.application"
ASGI_APPLICATION = "plumber_site.asgi.application"

# Database. implementation_plan.md §6 specifies PostgreSQL in production;
# backend_plan.md §12 names Neon as the host. One URL drives it, so the
# same code runs locally and in production with only the environment
# differing, and the credential lives nowhere but the environment (§6,
# §10 "Secrets never committed").
#
# No table exists yet - the §7 models and their migrations are still to
# come. This block only makes the connection available.
#
# Lower-case on purpose, and it must stay that way: Django's Settings only
# collects UPPERCASE names, so this never becomes `settings.DATABASE_URL`.
# That matters because the technical 500 page prints every setting and only
# masks names matching API|TOKEN|KEY|SECRET|PASS|SIGNATURE - "DATABASE_URL"
# matches none of those, so an uppercase name here would print the database
# password in full on any DEBUG traceback. The password inside DATABASES is
# masked, because that key *is* called PASSWORD.
_database_url = os.environ.get("DATABASE_URL", "").strip()

if _database_url:
    DATABASES = {
        "default": dj_database_url.parse(
            _database_url,
            # Reuse connections for ten minutes instead of opening one per
            # request. Neon's free tier suspends an idle compute, so a
            # reused connection can be dead on arrival; conn_health_checks
            # makes Django test and replace it rather than raise.
            conn_max_age=600,
            conn_health_checks=True,
            # Neon's default URL is the -pooler host, which is PgBouncer in
            # transaction-pooling mode. A server-side cursor does not
            # survive that, because consecutive statements can land on
            # different server connections. Django's own PostgreSQL notes
            # require this setting for any transaction-pooled connection,
            # and it is harmless on a direct one.
            disable_server_side_cursors=True,
        )
    }
elif DEBUG:
    # A fresh clone with no .env still runs: `manage.py check`,
    # `runserver` and the page tests need no PostgreSQL server.
    # Gitignored - see *.sqlite3 in .gitignore.
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    raise ImproperlyConfigured(
        "DATABASE_URL must be set when DJANGO_DEBUG is off. Production runs "
        "on PostgreSQL (implementation_plan.md §6); SQLite is a local-only "
        "fallback."
    )

# backend_plan.md §11 specifies the "default" alias, and it is left
# exactly as written.
#
# "throttle" is added by the security review (H2/H4). The original comment
# here claimed LocMemCache was "enough for a throttle whose only job is to
# blunt a flood from one address" - that was wrong in two ways. LocMemCache
# is per-process, so a second gunicorn worker gets its own empty counter
# and an attacker simply round-robins between them; and it is in-memory, so
# every deploy or cold start hands out a fresh allowance. A security counter
# has to be shared and durable, so it lives in Postgres.
#
# Cost is one indexed row read per throttled request. At this site's volume
# (tens of leads a month) that is irrelevant, and it buys a throttle that
# actually holds across workers and restarts. The table is created by
# core/migrations/0002.
CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    "throttle": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "core_throttle_cache",
        "TIMEOUT": 900,
        "OPTIONS": {
            # Counters are tiny and short-lived; keep the table from
            # growing without bound if a cull is ever missed.
            "MAX_ENTRIES": 10000,
            "CULL_FREQUENCY": 3,
        },
    },
}

# --- Request limits (security review H3) ---------------------------------
#
# `Lead.message` is a TextField with no length limit (backend_plan.md §6),
# the form did not cap it, and the textarea had no maxlength - so Django's
# 2.5MB default body size was the only ceiling on a single submission.
# Neon's free tier is 0.5GB, which is roughly 200 submissions to fill.
# Every request was also SHA-256'd in full and, on the fallback path,
# embedded whole into an email.
#
# 64KB is still enormous for "describe your plumbing problem" (the form
# itself now caps the field at 2000 characters) while leaving room for
# multibyte text and the other fields. The field-count cap blunts
# hash-collision style floods of junk keys.
DATA_UPLOAD_MAX_MEMORY_SIZE = 64 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 100

# --- Who is calling? (security review H2) --------------------------------
#
# Read core/security.py's client_ip() before changing these. The default of
# "" means REMOTE_ADDR, which is correct for local development and wrong
# behind a proxy - but wrong in the safe direction, because trusting a
# forwarding header that the deployment does not actually set would let any
# caller forge their own identity and opt out of the throttle entirely.
#
# Set at deploy time, once, to match the real topology:
#   Cloudflare proxying (orange cloud)  CLIENT_IP_HEADER=CF-Connecting-IP
#   Direct proxy (e.g. Nginx)           CLIENT_IP_HEADER=X-Forwarded-For
#                                       CLIENT_IP_TRUSTED_PROXIES=1
#   Cloudflare proxy + Nginx, via XFF   CLIENT_IP_HEADER=X-Forwarded-For
#                                       CLIENT_IP_TRUSTED_PROXIES=2
CLIENT_IP_HEADER = os.environ.get("CLIENT_IP_HEADER", "").strip()
CLIENT_IP_TRUSTED_PROXIES = int(
    os.environ.get("CLIENT_IP_TRUSTED_PROXIES", "1").strip() or 1
)

# --- Abuse limits --------------------------------------------------------
#
# The first two replace §7.1's bare "5 per IP per 10 minutes". That limit
# is kept as the cheap pre-validation gate, but it is no longer the only
# one: LEAD_MAX_PER_PHONE_PER_DAY is checked against the database, because
# every accepted lead costs a real WhatsApp Utility send (~₹0.13-0.18) and
# a replayed or slightly-mutated payload otherwise buys unlimited sends
# (security review H2/M2).
LEAD_MAX_PER_IP = int(os.environ.get("LEAD_MAX_PER_IP", "5"))
LEAD_RATE_WINDOW_SECONDS = int(os.environ.get("LEAD_RATE_WINDOW_SECONDS", "600"))
LEAD_MAX_PER_IP_PER_DAY = int(os.environ.get("LEAD_MAX_PER_IP_PER_DAY", "20"))
LEAD_MAX_PER_PHONE_PER_DAY = int(os.environ.get("LEAD_MAX_PER_PHONE_PER_DAY", "5"))
LEAD_DEDUPE_WINDOW_MINUTES = int(os.environ.get("LEAD_DEDUPE_WINDOW_MINUTES", "5"))

# Admin login lockout (security review H4). Ten wrong passwords from one
# address buys a fifteen-minute pause. Keyed on IP rather than username so
# that nobody can lock the owner out of his own console by guessing at his
# account deliberately.
ADMIN_LOGIN_MAX_FAILURES = int(os.environ.get("ADMIN_LOGIN_MAX_FAILURES", "10"))
ADMIN_LOGIN_LOCKOUT_SECONDS = int(os.environ.get("ADMIN_LOGIN_LOCKOUT_SECONDS", "900"))

# --- Owner alerts (backend_plan.md §8, §11) ------------------------------
#
# Read from the environment and never committed (§10 "Secrets never
# committed"): .env locally, and the environment in production. All default
# to empty, so a missing credential degrades to a failed alert that is
# logged and recorded on the Lead row - it can never stop a lead being
# saved (§7.1).
#
# WhatsApp Cloud API, called directly against Meta - "Path A", no BSP
# (§8). One-time console setup for these three values is §9.
WHATSAPP_ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN", "").strip()
WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "").strip()
# Bajarangi's own receiving number, digits only with country code, no '+'
# and no spaces - e.g. 91XXXXXXXXXX.
OWNER_WHATSAPP_NUMBER = os.environ.get("OWNER_WHATSAPP_NUMBER", "").strip()

# Brevo email, the free fallback used only when the WhatsApp call fails.
BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "").strip()
ALERT_FROM_EMAIL = os.environ.get(
    "ALERT_FROM_EMAIL", "leads@yourdomain.example"
).strip()
OWNER_ALERT_EMAIL = os.environ.get("OWNER_ALERT_EMAIL", "").strip()

# Absolute origin used to build the "Open in Admin" link in that email.
# core/context_processors.py reads the same variable for canonical URLs,
# where an empty value is meaningful; here a usable local default is.
SITE_URL = os.environ.get("SITE_URL", "").strip() or "http://127.0.0.1:8000"

LANGUAGE_CODE = "en-in"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
# Collected here by `manage.py collectstatic` for production serving.
# Gitignored - see /staticfiles/ in .gitignore.
STATIC_ROOT = BASE_DIR / "staticfiles"

# backend_plan.md §11 asks for
# whitenoise.storage.CompressedManifestStaticFilesStorage. It writes that
# as `STATICFILES_STORAGE`, which Django removed in 5.1; on Django 6.0.7
# the same instruction is expressed as the "staticfiles" entry of
# STORAGES. Both keys are listed because setting STORAGES replaces the
# default dict rather than merging into it.
#
# Hashed filenames apply only when DEBUG is off - HashedFilesMixin.url()
# returns the plain name under DEBUG - so local development and the
# existing page rendering are untouched. `collectstatic` must run at
# deploy time.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

# Security. §6: "Enforce HTTPS, secure cookies, CSRF protection".
# These apply as soon as DEBUG is off so a deployment is not left open by
# omission; they are skipped in local development because runserver is
# plain HTTP.
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"

# Security review L6. The CSRF token is read from the hidden input that
# {% csrf_token %} renders, never from document.cookie, so nothing on this
# site needs JavaScript to be able to read the cookie. Denying it costs
# nothing and removes one thing an injected script could walk off with.
CSRF_COOKIE_HTTPONLY = True

# Security review M4. Django's own filter masks settings whose names match
# API|AUTH|TOKEN|KEY|SECRET|PASS|SIGNATURE|HTTP_COOKIE. WHATSAPP_ACCESS_TOKEN
# and BREVO_API_KEY match by luck of naming; SENTRY_DSN and the owner's
# personal contact settings do not, and would print in full on a traceback
# page. This subclass extends the pattern to this project's own names.
DEFAULT_EXCEPTION_REPORTER_FILTER = "core.security.HardenedExceptionReporterFilter"

if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    CSRF_TRUSTED_ORIGINS = _list("DJANGO_CSRF_TRUSTED_ORIGINS")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
# Without an explicit LOGGING dict the "leads" logger (used in views,
# notifications and the retention command) falls through to Python's
# last-resort handler: no timestamps, no level label, and INFO messages
# silently dropped.  This gives every log line a consistent format and
# keeps INFO visible, while writing to stdout so Gunicorn / journald
# capture it the same way they already capture access logs.
#
# Django's own loggers are kept via disable_existing_loggers=False, so
# the default django.server / django.request handlers continue to work.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "{asctime} {levelname} [{name}] {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
    },
    "loggers": {
        "leads": {
            "handlers": ["console"],
            "level": "INFO",
        },
        "django": {
            "handlers": ["console"],
            "level": "INFO",
        },
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
