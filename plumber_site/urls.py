"""Root URL configuration.

Everything public lives in core/urls.py.

Django Admin is mounted at /admin/ because backend_plan.md requires it:
§6 makes it the place a lead's alert status is "visible and filterable",
§8's email fallback links to /admin/core/lead/<id>/change/ - so the
prefix has to be exactly this - and §10 restricts it with Django's
built-in is_staff flag. The §7 data model it needs now exists.
"""

from django.contrib import admin
from django.urls import include, path
from django_otp.admin import OTPAdminSite

admin.site.__class__ = OTPAdminSite

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
]
