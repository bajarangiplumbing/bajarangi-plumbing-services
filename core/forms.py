"""Server-side validation for the lead form.

backend_plan.md §7.1. The rule this serves is §1's: the server never
trusts the browser. Every check the frontend already does is done again
here, because the frontend's copy can be bypassed and this one cannot.

Three jobs beyond plain field validation:
  - `website` is a honeypot. It is not on the real form, so anything that
    fills it in is a bot.
  - `service_label` is whitelisted against the nine <option> labels the
    form actually offers, so it cannot be used to write arbitrary text
    into the lead record.
  - `clean_phone` normalises the shapes Indian numbers really arrive in
    (+91 prefix, leading 0, spaces, dashes) down to ten digits before
    validating, rather than rejecting a valid number for its formatting.

One addition from the security review (H3): `message` is capped. §6
models it as a TextField, which has no length limit, and §7.1's form did
not constrain it either - so a single submission could carry as much text
as Django's request-body ceiling allowed, all of it stored, hashed, and
embedded whole into the fallback email. The cap is applied here rather
than on the model so the §6 schema stays byte-for-byte as specified and
no migration is needed: every write path to Lead goes through this form.
"""

import re

from django import forms

from core.models import BookingRequest, Lead

SERVICE_CHOICES = [
    "Leak Detection & Repair",
    "Water Tank & Motor Work",
    "WC / Toilet Fittings",
    "Washbasin & Bath Accessories Fittings",
    "Bathroom Tile Grouting",
    "New Bathroom Installation & Full Renovation",
    "Drain & blockage cleaning",
    "Emergency fix",
    "Not sure / other",
]  # exact copy of the nine selectable service labels in both forms

# Generous for "describe your plumbing problem" - the longest genuine
# complaint is a short paragraph - and small enough that it cannot be used
# to fill the database or bloat an alert email. Mirrored by the textarea's
# maxlength attribute, which is a courtesy to honest users, not a control.
MAX_MESSAGE_CHARS = 2000

# The four <option> labels in the booking form's "Preferred time" select.
# Whitelisted for the same reason service_label is: it is a free-text
# column fed from a <select>, and a direct POST can put anything in it.
SLOT_CHOICES = [
    "Morning (9:30 – 13:00)",
    "Afternoon (13:00 – 16:00)",
    "Evening (16:00 – 19:00)",
    "Any time that day",
]

# Start-of-slot hour, used to build BookingRequest.preferred_datetime from
# the chosen date plus slot. "Any time that day" gets the start of the
# working day rather than midnight, because midnight would sort and display
# as the previous evening in Asia/Kolkata-local admin views.
SLOT_START_HOUR = {
    "Morning (9:30 – 13:00)": 9,
    "Afternoon (13:00 – 16:00)": 13,
    "Evening (16:00 – 19:00)": 16,
    "Any time that day": 9,
}


class LeadForm(forms.ModelForm):
    website = forms.CharField(
        required=False,
        widget=forms.HiddenInput,
        # Always empty in legitimate traffic; bounded so a bot cannot use
        # the honeypot itself as the payload.
        max_length=100,
    )
    # Declared explicitly to add the cap the model field cannot express
    # without a schema change (H3). Textarea keeps the widget the ModelForm
    # would have chosen for a TextField.
    message = forms.CharField(
        max_length=MAX_MESSAGE_CHARS,
        widget=forms.Textarea,
        error_messages={
            "max_length": (
                f"Please keep the description under {MAX_MESSAGE_CHARS} characters."
            )
        },
    )

    class Meta:
        model = Lead
        fields = ["customer_name", "phone", "locality", "service_label", "message"]

    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise forms.ValidationError("Spam detected.")
        return ""

    def clean_service_label(self):
        val = self.cleaned_data.get("service_label") or SERVICE_CHOICES[0]
        return val if val in SERVICE_CHOICES else SERVICE_CHOICES[0]

    def clean_phone(self):
        raw = self.cleaned_data["phone"]
        digits = "".join(ch for ch in raw if ch.isdigit())
        if len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        if len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]
        if not re.match(r"^[6-9]\d{9}$", digits):
            raise forms.ValidationError("Enter a valid 10-digit Indian mobile number.")
        return digits

class BookingForm(forms.ModelForm):
    website = forms.CharField(
        required=False,
        widget=forms.HiddenInput,
        max_length=100,
    )
    message = forms.CharField(
        max_length=MAX_MESSAGE_CHARS,
        required=False,
        widget=forms.Textarea,
    )

    class Meta:
        model = BookingRequest
        # service_label, preferred_date and preferred_time_slot were added
        # during the compliance review. They used to be concatenated into
        # `message` as free text by the view, which meant the customer's
        # email address was stored twice - once in its own column and once
        # inside a text blob that any erasure routine keyed on columns
        # would miss.
        fields = [
            "customer_name",
            "phone",
            "email",
            "address",
            "locality",
            "service_label",
            "preferred_date",
            "preferred_time_slot",
            "urgency",
            "message",
        ]

    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise forms.ValidationError("Spam detected.")
        return ""

    def clean_service_label(self):
        val = self.cleaned_data.get("service_label") or ""
        return val if val in SERVICE_CHOICES else ""

    def clean_preferred_time_slot(self):
        val = self.cleaned_data.get("preferred_time_slot") or ""
        return val if val in SLOT_CHOICES else ""

    # Duplicated from LeadForm rather than shared, to keep this change
    # additive. If a third form ever appears, lift both into a mixin - two
    # copies of a validator is the point at which they start to drift.
    def clean_phone(self):
        raw = self.cleaned_data["phone"]
        digits = "".join(ch for ch in raw if ch.isdigit())
        if len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        if len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]
        if not re.match(r"^[6-9]\d{9}$", digits):
            raise forms.ValidationError("Enter a valid 10-digit Indian mobile number.")
        return digits

