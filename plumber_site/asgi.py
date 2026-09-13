"""ASGI entry point for production serving (implementation_plan.md §6)."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "plumber_site.settings")

application = get_asgi_application()
