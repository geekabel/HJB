from django import forms
from django.core.validators import MaxValueValidator, MinValueValidator

from sms.service import ready_providers

from .models import ResidenceSettings, SmsChoice

RETENTION_FIELDS = [
    "former_residents_days",
    "report_photos_days",
    "meetings_days",
    "direct_messages_days",
    "deliveries_days",
    "wifi_accesses_days",
    "audit_log_days",
    "codes_days",
]


class ResidenceSettingsForm(forms.ModelForm):
    # The version of the row the form was loaded from: two people saving at
    # the same time must not silently undo each other.
    version = forms.CharField(widget=forms.HiddenInput, required=False)
    confirm_shorter = forms.BooleanField(
        label="Je confirme : avec une durée plus courte, les données plus anciennes "
        "seront supprimées à la prochaine suppression quotidienne.",
        required=False,
    )

    class Meta:
        model = ResidenceSettings
        fields = [
            "organization_name",
            "organization_address",
            "privacy_contact",
            "emergency_phone",
            "sms_provider",
            "summary_hour",
            *RETENTION_FIELDS,
        ]
        widgets = {
            "organization_address": forms.Textarea(attrs={"rows": 3}),
            "summary_hour": forms.Select(choices=[(hour, f"{hour} h") for hour in range(7, 12)]),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only the services whose keys are on the server, the server's one,
        # and "none". The current choice stays listed even if its keys went.
        offered = {SmsChoice.SERVER, SmsChoice.PAUSED, self.instance.sms_provider}
        offered.update(ready_providers())
        self.fields["sms_provider"].choices = [
            (value, label) for value, label in SmsChoice.choices if value in offered
        ]
        self.fields["sms_provider"].widget = forms.RadioSelect(
            choices=self.fields["sms_provider"].choices
        )
        for name in RETENTION_FIELDS:
            field = self.fields[name]
            field.widget.attrs["inputmode"] = "numeric"
            for validator in ResidenceSettings._meta.get_field(name).validators:
                if isinstance(validator, MinValueValidator):
                    field.widget.attrs["min"] = validator.limit_value
                if isinstance(validator, MaxValueValidator):
                    field.widget.attrs["max"] = validator.limit_value
        self.fields["version"].initial = self.instance.updated_at.isoformat()

    def clean(self):
        cleaned = super().clean()
        version = self.data.get("version", "")
        if self.instance.pk and version != self.instance.updated_at.isoformat():
            raise forms.ValidationError(
                "Quelqu'un a changé les réglages pendant ce temps. "
                "Rechargez la page, puis refaites vos changements."
            )
        shorter = [
            str(self.fields[name].label)
            for name in RETENTION_FIELDS
            if cleaned.get(name) is not None and cleaned[name] < getattr(self.instance, name)
        ]
        if shorter and not cleaned.get("confirm_shorter"):
            self.add_error(
                "confirm_shorter",
                f"Durée plus courte pour : {', '.join(shorter)}. Cochez pour confirmer.",
            )
        return cleaned

    def retention_fields(self):
        return [self[name] for name in RETENTION_FIELDS]

    def changes(self):
        """[label, before, after] of each field changed, for the audit log."""
        found = []
        for name in self.changed_data:
            if name in ("version", "confirm_shorter"):
                continue
            field = self.fields[name]
            before, after = self.initial.get(name), self.cleaned_data.get(name)
            if hasattr(field, "choices") and name == "sms_provider":
                labels = dict(SmsChoice.choices)
                before, after = labels.get(before, before), labels.get(after, after)
            before, after = _short(before), _short(after)
            if before == after:  # a change beyond the shown length
                after = f"{after} (texte modifié)"
            found.append([str(field.label), before, after])
        return found


def _short(value):
    text = " ".join(str(value if value is not None else "").split())
    return text if len(text) <= 80 else text[:79] + "…"
