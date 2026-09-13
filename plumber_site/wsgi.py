"""WSGI entry point for production serving (implementation_plan.md §6)."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "plumber_site.settings")

application = get_wsgi_application()
