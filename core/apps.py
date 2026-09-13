from django.apps import AppConfig


class CoreConfig(AppConfig):
    """The public site and the lead-capture backend.

    implementation_plan.md §6 scopes this app as "Pages, services, leads,
    bookings, forms". The pages are in templates/, static/, views.py and
    urls.py; the leads half is models.py, forms.py, notifications.py and
    the /api/lead/ view, built per backend_plan.md §6-§8.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Bajarangi Plumbing Services site"

    def ready(self):
        # Importing the module connects its two @receiver hooks for
        # user_login_failed / user_logged_in, which is what feeds the
        # admin login lockout in core/security.py. Without this import the
        # middleware's counter is never incremented and the lockout
        # silently never triggers.
        # Same pattern, same reason: the @register decorators in
        # core/checks.py only attach to Django's check registry when the
        # module is imported. Without this line the compliance checks are
        # dead code and a production build would pass while the site still
        # published a placeholder phone number.
        from core import checks, security  # noqa: F401
