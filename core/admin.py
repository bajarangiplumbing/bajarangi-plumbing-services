"""Django Admin - the staff console for leads.

backend_plan.md depends on Admin in three places, and this module exists
to satisfy exactly those three, no more:

  §6  `whatsapp_alert_status` must be "visible and filterable in Django
      Admin", and §8's closing paragraph wants `email_alert_status` to
      double as a "did anything go wrong?" column you can filter on.
  §8  the email fallback links straight to
      /admin/core/lead/<id>/change/, so that URL has to resolve.
  §10 "Restricted Django Admin access | Django's built-in is_staff
      flag" - Admin's own default, so nothing is added for it here.

One addition beyond those three: `export_as_csv` on LeadAdmin and
BookingRequestAdmin, so leads/bookings can leave the box without database
access.  Each export logs who ran it, when, and how many records, via
both the server log and Django's admin LogEntry (visible in "Recent
Actions" on the dashboard).

Everything else is stock ModelAdmin. The only fields marked read-only
are the ones the server writes rather than a person: the delivery
statuses, Meta's message ID, the anti-spam values, and the consent pair.
Editing those by hand would falsify the record of what was actually
received, consented to, and sent.
"""

import csv
import logging

from django.contrib import admin
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponse

from core.models import (
    BookingRequest,
    Lead,
    Service,
    ServiceArea,
    Technician,
    Testimonial,
)

logger = logging.getLogger("leads")


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = (
        "customer_name",
        "phone",
        "locality",
        "service_label",
        "status",
        "whatsapp_alert_status",
        "email_alert_status",
        "created_at",
    )
    # §6 / §8: both alert statuses filterable.
    list_filter = (
        "status",
        "whatsapp_alert_status",
        "email_alert_status",
        "source",
        "created_at",
    )
    search_fields = ("customer_name", "phone", "locality", "message")
    date_hierarchy = "created_at"
    list_select_related = ("assigned_technician",)
    autocomplete_fields = ("assigned_technician",)
    # Triage is the one thing worth doing without opening each lead.
    list_editable = ("status",)
    readonly_fields = (
        "created_at",
        "submission_ip",
        "dedupe_key",
        "consent_given",
        "consent_at",
        # Which wording the customer agreed to. Evidence, so not editable.
        "consent_notice_version",
        "whatsapp_alert_status",
        "whatsapp_message_id",
        "email_alert_status",
    )
    actions = ("export_as_csv",)

    @admin.action(description="Export selected leads as CSV")
    def export_as_csv(self, request, queryset):
        """Stream the selected leads out as a spreadsheet-ready CSV."""
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="leads.csv"'
        writer = csv.writer(response)
        writer.writerow(
            ["Name", "Phone", "Locality", "Service", "Message", "Status", "Created"]
        )
        for lead in queryset:
            writer.writerow(
                [
                    lead.customer_name,
                    lead.phone,
                    lead.locality,
                    lead.service_label,
                    lead.message,
                    lead.status,
                    lead.created_at,
                ]
            )

        # --- audit trail -------------------------------------------------
        count = queryset.count()
        logger.info(
            "CSV export: user=%s model=Lead count=%d ip=%s",
            request.user,
            count,
            request.META.get("REMOTE_ADDR", "unknown"),
        )
        LogEntry.objects.log_action(
            user_id=request.user.pk,
            content_type_id=ContentType.objects.get_for_model(Lead).pk,
            object_id="",
            object_repr=f"CSV export \u2014 {count} lead(s)",
            action_flag=CHANGE,
            change_message=f"Exported {count} lead(s) as CSV.",
        )
        return response


@admin.register(BookingRequest)
class BookingRequestAdmin(admin.ModelAdmin):
    list_display = (
        "customer_name",
        "phone",
        "locality",
        "preferred_datetime",
        "status",
        "created_at",
    )
    list_filter = ("status", "source", "created_at")
    search_fields = ("customer_name", "phone", "locality", "message")
    date_hierarchy = "created_at"
    list_select_related = ("service", "assigned_technician")
    autocomplete_fields = ("service", "assigned_technician")
    # Consent fields are read-only here for the same reason they already
    # were on LeadAdmin: they are the evidence that consent was given, and
    # evidence a member of staff can edit is not evidence. Before the
    # September 2026 review this admin let anyone with access tick
    # consent_given or backdate consent_at by hand, while LeadAdmin
    # correctly forbade it - an inconsistency that would have been
    # impossible to explain to the Data Protection Board.
    #
    # Withdrawal of consent is handled by deleting the record (or by the
    # retention job), not by unticking the box, so nothing legitimate
    # needs these to be writable.
    #
    # The alert-status fields are read-only because they are written by
    # core.notifications, not by a human; a hand-edited "sent" would hide a
    # delivery failure.
    readonly_fields = (
        "created_at",
        "updated_at",
        "consent_given",
        "consent_at",
        "consent_notice_version",
        "whatsapp_alert_status",
        "whatsapp_message_id",
        "email_alert_status",
    )
    actions = ("export_as_csv",)

    @admin.action(description="Export selected bookings as CSV")
    def export_as_csv(self, request, queryset):
        """Stream the selected booking requests out as a spreadsheet-ready CSV."""
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="bookings.csv"'
        writer = csv.writer(response)
        writer.writerow(
            [
                "Name",
                "Phone",
                "Email",
                "Address",
                "Locality",
                "Service",
                "Preferred Date",
                "Time Slot",
                "Message",
                "Status",
                "Created",
            ]
        )
        for booking in queryset:
            writer.writerow(
                [
                    booking.customer_name,
                    booking.phone,
                    booking.email,
                    booking.address,
                    booking.locality,
                    booking.service_label,
                    booking.preferred_date,
                    booking.preferred_time_slot,
                    booking.message,
                    booking.status,
                    booking.created_at,
                ]
            )

        # --- audit trail -------------------------------------------------
        count = queryset.count()
        logger.info(
            "CSV export: user=%s model=BookingRequest count=%d ip=%s",
            request.user,
            count,
            request.META.get("REMOTE_ADDR", "unknown"),
        )
        LogEntry.objects.log_action(
            user_id=request.user.pk,
            content_type_id=ContentType.objects.get_for_model(BookingRequest).pk,
            object_id="",
            object_repr=f"CSV export \u2014 {count} booking(s)",
            action_flag=CHANGE,
            change_message=f"Exported {count} booking(s) as CSV.",
        )
        return response


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "category",
        "starting_price_inr",
        "active",
        "display_order",
    )
    list_filter = ("active", "category")
    # Also backs BookingRequestAdmin's autocomplete on `service`.
    search_fields = ("title", "short_description")
    prepopulated_fields = {"slug": ("title",)}


@admin.register(ServiceArea)
class ServiceAreaAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "state", "active", "display_order")
    list_filter = ("active", "city")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Technician)
class TechnicianAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "active")
    list_filter = ("active",)
    # Backs the autocomplete on `assigned_technician` in both admins above.
    search_fields = ("name", "phone")


@admin.register(Testimonial)
class TestimonialAdmin(admin.ModelAdmin):
    list_display = ("display_name", "rating", "source", "approved", "review_date")
    list_filter = ("approved", "rating", "source")
    search_fields = ("display_name", "review_text")
