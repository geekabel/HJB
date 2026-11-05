from django import forms

from .models import Absence, EducatorSettings


class SettingsForm(forms.ModelForm):
    class Meta:
        model = EducatorSettings
        fields = ["slot_minutes", "notice"]
        help_texts = {
            "notice": "« La veille » : pas de rendez-vous pris le jour même.",
        }


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
        if first and last and last < first:
            self.add_error("last_day", "Le dernier jour ne peut pas précéder le premier.")
        return data
