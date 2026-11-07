from django import forms

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
            self.fields[name].widget.attrs["inputmode"] = "numeric"

    def retention_fields(self):
        return [self[name] for name in RETENTION_FIELDS]

    def changes(self):
        """[label, before, after] of each field changed, for the audit log."""
        found = []
        for name in self.changed_data:
            field = self.fields[name]
            before, after = self.initial.get(name), self.cleaned_data.get(name)
            if hasattr(field, "choices") and name == "sms_provider":
                labels = dict(SmsChoice.choices)
                before, after = labels.get(before, before), labels.get(after, after)
            found.append([str(field.label), _short(before), _short(after)])
        return found


def _short(value):
    text = " ".join(str(value if value is not None else "").split())
    return text if len(text) <= 60 else text[:59] + "…"
