from django import forms

from .models import EducatorSettings


class SettingsForm(forms.ModelForm):
    class Meta:
        model = EducatorSettings
        fields = ["slot_minutes", "notice"]
        help_texts = {
            "notice": "« La veille » : pas de rendez-vous pris le jour même.",
        }
