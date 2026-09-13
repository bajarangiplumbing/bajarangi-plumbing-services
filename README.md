# Bajarangi Plumbing Services

Django-powered website and lead-capture backend for a plumbing services
business in Bhubaneswar, Odisha.

## What's built

### Public website — 13 pages

| # | URL | Purpose |
|---|-----|---------|
| 1 | `/` | Home — hero, services overview, trust signals, generic contact CTA |
| 2–7 | `/services/leak-repair/`, `water-tank/`, `wc-toilet-fittings/`, `washbasin-bath-accessories/`, `bathroom-tile-grouting/`, `bathroom-installation-renovation/` | One page per advertised service |
| 8 | `/about/` | Business story and credentials |
| 9 | `/contact/` | Phone, WhatsApp, callback request, lead form |
| 10–13 | `/privacy/`, `/cookies/`, `/terms/`, `/refunds/` | Legal / compliance pages |

Plus non-page endpoints:

- `POST /api/lead/` — lead submission (throttled per IP and per phone)
- `POST /api/booking/` — booking request submission
- `/healthz/` — uptime probe for monitoring
- `/robots.txt` — crawl directives (disallows `/admin/`, `/api/*`)
- `/sitemap.xml` — auto-generated from Django's sitemap framework

### Backend

- **Lead & booking capture** — form submissions saved to PostgreSQL,
  deduplicated, with per-IP and per-phone-number rate limiting.
- **Owner alerts** — WhatsApp Cloud API (primary) + Brevo email (fallback).
  Both credentials read from environment variables; a failed alert never
  blocks the lead from being saved.
- **Django Admin** with 2FA (TOTP via `django-otp`), export-to-CSV with
  audit logging, and admin login brute-force lockout.
- **Data retention** — `manage.py purge_expired_leads` enforces the
  published retention periods (configurable via env vars). Designed to run
  nightly via cron.
- **Security hardening** — CSP + Permissions-Policy headers, CSRF,
  HTTPS enforcement (when `DEBUG=False`), `SECRET_KEY` from env,
  `HardenedExceptionReporterFilter` that masks project-specific secrets,
  Sentry with PII scrubbing disabled.

### CI/CD (GitLab)

- SAST, Secret Detection, Dependency Scanning (built-in templates)
- Nightly encrypted database backup (AES-256, fails closed without passphrase)

### SEO

- `robots.txt` and `sitemap.xml` both derive their domain from the `SITE_URL`
  environment variable — set it once and both files update automatically.
- Canonical tags, Open Graph meta, and JSON-LD structured data on every page
  (rendered via `base.html` using the same `SITE_URL`).

## What's pending

These are deployment-time tasks, not code changes:

| Task | Notes |
|------|-------|
| **EC2 instance setup** | `deploy/gunicorn.service`, `deploy/nginx.conf`, and `deploy/crontab.txt` are ready as templates |
| **Domain + SSL** | `nginx.conf` has `server_name _;` (catch-all) and a TODO for Certbot |
| **Set `SITE_URL`** | Once the domain is live, set `SITE_URL=https://yourdomain.com` in `.env` |
| **Cron scheduling** | `purge_expired_leads` and `clearsessions` — commands in `deploy/crontab.txt` |
| **Real phone number** | Set `SETU_PHONE_DISPLAY` / `SETU_PHONE_TEL` / `SETU_WA_NUMBER` in `.env` |
| **Legal identity** | Set `BUSINESS_PROPRIETOR`, `BUSINESS_ADDRESS_STREET`, `BUSINESS_EMAIL` — `manage.py check` will refuse to start in production without them |
| **Test suite** | No automated tests exist yet — this is the largest code-quality gap |

> **Note:** The deployment target moved from Render to AWS EC2. The
> `render.yaml` that existed in the initial commit was intentionally
> removed — the `deploy/` directory contains the replacement configs
> (systemd, nginx, cron).

## Local development

### Prerequisites

- Python 3.12 (pinned in `.python-version`)
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### Setup

```bash
# Clone and enter the project
git clone https://gitlab.com/kiro1gudu/bajarangi_plumbing.git
cd bajarangi_plumbing

# Create virtual environment and install dependencies
uv sync            # or: python -m venv .venv && pip install -r requirements.txt

# Copy environment template
cp .env.example .env
# Edit .env — at minimum set DJANGO_DEBUG=True (already the default in .env.example)

# Run migrations (uses SQLite locally when DATABASE_URL is blank)
.venv/bin/python manage.py migrate

# Start the dev server
.venv/bin/python manage.py runserver
```

The site is at [http://127.0.0.1:8000](http://127.0.0.1:8000).

### Key commands

```bash
# Lint
.venv/bin/python -m ruff check .

# System checks (catches missing env vars that would block production)
.venv/bin/python manage.py check

# Check for un-generated migrations
.venv/bin/python manage.py makemigrations --check --dry-run

# Create a superuser for Django Admin
.venv/bin/python manage.py createsuperuser
# Then visit /admin/ and set up a TOTP device for 2FA
```

### Environment variables

All configuration is via environment variables, documented in
[`.env.example`](.env.example). The file is 198 lines with inline
explanation of every variable, its purpose, and its security implications.

Key groups:
- **Django core** — `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DATABASE_URL`
- **Site identity** — `SITE_URL`, `SETU_PHONE_*`
- **Legal identity** — `BUSINESS_PROPRIETOR`, `BUSINESS_ADDRESS_*`, `BUSINESS_EMAIL`
- **Alerts** — `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `OWNER_WHATSAPP_NUMBER`, `BREVO_API_KEY`
- **Security** — `SENTRY_DSN`, `CLIENT_IP_HEADER`, rate-limit tuning
- **Data retention** — `RETENTION_ENQUIRY_DAYS`, `RETENTION_JOB_DAYS`, `RETENTION_IP_DAYS`

## Project structure

```
plumber_site/          Django project (settings, root URLs, WSGI/ASGI)
core/                  The single app
  admin.py             Admin config with 2FA, CSV export, audit logging
  checks.py            Deploy-blocking system checks for legal identity
  context_processors.py  Site-wide contact/legal identity (single source of truth)
  forms.py             Lead and booking forms with validation
  management/commands/  purge_expired_leads management command
  models.py            Lead, BookingRequest models
  notifications.py     WhatsApp + Brevo alert dispatch
  security.py          CSP middleware, rate limiting, IP resolution
  sitemaps.py          Django sitemap framework integration
  static/              CSS, JS, images
  templates/           All HTML (base, pages, partials)
  urls.py              All public routes + API endpoints
  views.py             Page views, form handlers, healthz
deploy/                Production deployment templates (gunicorn, nginx, cron)
PRD/                   Product requirements (gitignored, not deployed)
```

## Tech stack

| Layer | Choice |
|-------|--------|
| Framework | Django 6.0 |
| Database | PostgreSQL 18 (Neon, pooled) / SQLite locally |
| Static files | WhiteNoise with hashed filenames |
| 2FA | django-otp (TOTP) |
| Alerts | WhatsApp Cloud API + Brevo (email fallback) |
| Error monitoring | Sentry |
| CI/CD | GitLab CI (SAST, Secret Detection, Dependency Scanning) |
| Linting | Ruff |
| Deployment target | AWS EC2 + Nginx + Gunicorn |
