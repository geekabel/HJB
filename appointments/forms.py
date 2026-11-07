from datetime import timedelta

from django import forms
from django.utils import timezone

from .models import Absence, EducatorSettings


class SettingsForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["reply_hours"].required = False  # empty: the usual hours

    def clean_reply_hours(self):
        value = " ".join(self.cleaned_data.get("reply_hours", "").split())
        return value or EducatorSettings._meta.get_field("reply_hours").default

    class Meta:
        model = EducatorSettings
        fields = ["slot_minutes", "notice", "remind_residents", "reply_hours"]
        help_texts = {
            "notice": "«\u00a0La veille\u00a0» : pas de rendez-vous pris le jour même.",
        }


MAX_AHEAD = 366  # days


class AbsenceForm(forms.ModelForm):
    class Meta:
        model = Absence
        fields = ["first_day", "last_day"]
        widgets = {
            "first_day": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "last_day": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def clean(self):
        data = super().clean()
        first, last = data.get("first_day"), data.get("last_day")
        today = timezone.localdate()
        if first and last and last < first:
            self.add_error("last_day", "Le dernier jour ne peut pas précéder le premier.")
        elif last and last < today:
            self.add_error("last_day", "Cette absence est déjà passée.")
        elif first and first > today + timedelta(days=MAX_AHEAD):
            self.add_error("first_day", "Une absence se déclare un an à l'avance au plus.")
        return data
