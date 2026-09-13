"""Data model for the lead-capture backend.

Verbatim from backend_plan.md §6, which is itself
implementation_plan.md §7's model list plus the three notification-status
fields §6 adds so the "bulletproof" guarantee is verifiable rather than
assumed.

Nothing here stores payment-card data, per backend_plan.md §6's closing
line and implementation_plan.md's explicit rule.
"""

from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

phone_validator = RegexValidator(
    regex=r"^[6-9]\d{9}$",
    message="Enter a valid 10-digit Indian mobile number.",
)


class Service(models.Model):
    title = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    short_description = models.CharField(max_length=200, blank=True)
    full_description = models.TextField(blank=True)
    category = models.CharField(max_length=80, blank=True)
    starting_price_inr = models.PositiveIntegerField(null=True, blank=True)
    active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)
    seo_title = models.CharField(max_length=160, blank=True)
    seo_description = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["display_order", "title"]

    def __str__(self):
        return self.title


class ServiceArea(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    city = models.CharField(max_length=80, default="Bhubaneswar")
    state = models.CharField(max_length=80, default="Odisha")
    active = models.BooleanField(default=True)
    content = models.TextField(
        blank=True,
        help_text=(
            "Locality-specific content, 250+ words before publishing a page "
            "for this area."
        ),
    )
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["display_order", "name"]

    def __str__(self):
        return self.name


class Technician(models.Model):
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=15, validators=[phone_validator])
    active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return self.name


class LeadStatus(models.TextChoices):
    NEW = "new", "New"
    CONTACTED = "contacted", "Contacted"
    CONFIRMED = "confirmed", "Confirmed"
    ASSIGNED = "assigned", "Assigned"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"
    SPAM = "spam", "Spam"


class LeadSource(models.TextChoices):
    WEBSITE_FORM = "website_form", "Website form"
    PHONE = "phone", "Phone call"
    WHATSAPP_DIRECT = "whatsapp_direct", "WhatsApp direct message"
    OTHER = "other", "Other"


class AlertStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SENT = "sent", "Sent"
    FAILED = "failed", "Failed"
    NOT_APPLICABLE = "n_a", "Not applicable"


class Lead(models.Model):
    """
    Maps 1:1 to index.html's #leadForm. Field-by-field:
      #f-name    -> customer_name
      #f-phone   -> phone (server re-validates; never trust the client)
      #f-area    -> locality
      #f-service -> service_label (free text copy of the <option> chosen)
      #f-issue   -> message
      #f-consent -> consent_given + consent_at (checked but never stored by
                    the frontend today - the backend is where it's finally
                    recorded, since it's the legally meaningful copy)
    """

    customer_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=15, validators=[phone_validator])
    full_address = models.CharField(max_length=255, blank=True)
    locality = models.CharField(max_length=120)
    service_label = models.CharField(max_length=120, blank=True)
    message = models.TextField()

    source = models.CharField(
        max_length=20, choices=LeadSource.choices, default=LeadSource.WEBSITE_FORM
    )
    contact_preference = models.CharField(max_length=20, default="whatsapp")
    consent_given = models.BooleanField(default=False)
    consent_at = models.DateTimeField(null=True, blank=True)
    # WHICH wording was agreed to. DPDP Act 2023 s.6(1) requires consent to
    # be informed and specific; that is unprovable a year later if the only
    # record is a boolean and the on-page text has since been reworded.
    # Set from core.context_processors.CONSENT_NOTICE_VERSION, which the
    # form submits as a hidden field.
    consent_notice_version = models.CharField(
        max_length=32,
        blank=True,
        help_text=(
            "Version stamp of the consent wording shown to the customer. "
            "Read-only evidence - never edit it."
        ),
    )

    urgency = models.CharField(
        max_length=20,
        blank=True,
        help_text="e.g. emergency / today / this week / flexible",
    )
    status = models.CharField(
        max_length=20, choices=LeadStatus.choices, default=LeadStatus.NEW
    )
    assigned_technician = models.ForeignKey(
        Technician, null=True, blank=True, on_delete=models.SET_NULL
    )
    internal_notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    contacted_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    # Anti-spam / anti-duplicate support (see §8)
    submission_ip = models.GenericIPAddressField(null=True, blank=True)
    dedupe_key = models.CharField(max_length=64, db_index=True, blank=True)

    # NEW - notification delivery tracking, so "bulletproof" is verifiable,
    # not just assumed. Visible and filterable in Django Admin.
    whatsapp_alert_status = models.CharField(
        max_length=10, choices=AlertStatus.choices, default=AlertStatus.PENDING
    )
    whatsapp_message_id = models.CharField(
        max_length=100,
        blank=True,
        help_text="Meta's message ID, useful for delivery-status webhooks later.",
    )
    email_alert_status = models.CharField(
        max_length=10, choices=AlertStatus.choices, default=AlertStatus.PENDING
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "created_at"])]

    def __str__(self):
        # ID + date only: customer_name and phone were here before, but
        # Django's LogEntry copies __str__ into object_repr on every admin
        # action, creating a personal-data shadow outside the retention flow.
        date = timezone.localtime(self.created_at).strftime("%d %b %Y") if self.created_at else "unsaved"
        return f"Lead #{self.pk} \u2014 {date}"


class BookingRequest(models.Model):
    """The longer scheduling form, live at /api/booking/.

    The original docstring said "NOT BUILT ... so the schema is ready when
    a longer scheduling form is added". The form and the endpoint both
    exist, so that is no longer true.

    Four fields were added during the September 2026 compliance review, all
    to stop personal data being smuggled into `message` as free text:

      service_label       the chosen service. `service` is a FK to Service,
                          which BookingForm never populates and which has
                          no seeded rows, so the customer's choice survived
                          only inside the message blob.
      preferred_date      a real date column.
      preferred_time_slot the human slot label ("Morning (8:00 - 12:00)"),
                          which a bare datetime cannot express.
      consent_notice_version   see the note on Lead.

    Plus the three alert-status fields Lead already had. Their absence is
    why core.views.submit_booking had to fake a `MockLead` whose save() was
    a no-op, which silently discarded every booking's delivery status and
    made the owner's fallback email link to an unrelated Lead row.

    Why the email-into-message duplication mattered: an erasure or export
    routine keyed on columns would have missed the copy, so "delete my
    data" would have left the address sitting in a text field.
    """

    customer_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=15, validators=[phone_validator])
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=255)
    locality = models.CharField(max_length=120)
    service = models.ForeignKey(
        Service, null=True, blank=True, on_delete=models.SET_NULL
    )
    service_label = models.CharField(max_length=120, blank=True)
    # Kept and now actually populated. Was always NULL because nothing ever
    # wrote to it: the form's date and slot went into `message` instead.
    preferred_datetime = models.DateTimeField(null=True, blank=True)
    preferred_date = models.DateField(null=True, blank=True)
    preferred_time_slot = models.CharField(max_length=40, blank=True)
    urgency = models.CharField(max_length=20, blank=True)
    message = models.TextField(blank=True)

    consent_given = models.BooleanField(default=False)
    consent_at = models.DateTimeField(null=True, blank=True)
    consent_notice_version = models.CharField(
        max_length=32,
        blank=True,
        help_text=(
            "Version stamp of the consent wording shown to the customer. "
            "Read-only evidence - never edit it."
        ),
    )
    whatsapp_alert_status = models.CharField(
        max_length=10, choices=AlertStatus.choices, default=AlertStatus.PENDING
    )
    whatsapp_message_id = models.CharField(max_length=100, blank=True)
    email_alert_status = models.CharField(
        max_length=10, choices=AlertStatus.choices, default=AlertStatus.PENDING
    )
    source = models.CharField(
        max_length=20, choices=LeadSource.choices, default=LeadSource.WEBSITE_FORM
    )
    status = models.CharField(
        max_length=20, choices=LeadStatus.choices, default=LeadStatus.NEW
    )
    assigned_technician = models.ForeignKey(
        Technician, null=True, blank=True, on_delete=models.SET_NULL
    )
    confirmed_visit_time = models.DateTimeField(null=True, blank=True)
    quoted_amount_inr = models.PositiveIntegerField(null=True, blank=True)
    internal_notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        # Same rationale as Lead.__str__ above.
        date = timezone.localtime(self.created_at).strftime("%d %b %Y") if self.created_at else "unsaved"
        return f"Booking #{self.pk} \u2014 {date}"


class Testimonial(models.Model):
    display_name = models.CharField(max_length=120)
    rating = models.PositiveSmallIntegerField(default=5)
    review_text = models.TextField()
    review_date = models.DateField(null=True, blank=True)
    source = models.CharField(
        max_length=20, default="direct", help_text="'google' or 'direct'"
    )
    approved = models.BooleanField(
        default=False,
        help_text=(
            "Only approved+genuine reviews should ever render on the live site."
        ),
    )
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["display_order", "-review_date"]

    def __str__(self):
        return f"{self.display_name} ({self.rating}★)"
