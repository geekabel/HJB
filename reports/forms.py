"""Form of a report (card T30). The template draws the choices as tiles."""

from django import forms

from . import photos
from .models import Report


class MultipleFileInput(forms.ClearableFileInput):
    """Several photos in one field (Django docs, "Uploading multiple files")."""

    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            return [single_file_clean(d, initial) for d in data if d]
        return [single_file_clean(data, initial)] if data else []


class ReportForm(forms.Form):
    ACCESS_CHOICES = [
        ("yes", "Vous pouvez entrer si je suis absent"),
        ("no", "Je veux être présent"),
    ]

    category = forms.ChoiceField(
        label="Quel est le problème ?",
        choices=Report.Category.choices,
        widget=forms.RadioSelect,
        error_messages={"required": "Choisissez le type de problème."},
    )
    description = forms.CharField(
        label="Décrivez en quelques mots",
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3}),
        error_messages={"required": "Dites en quelques mots ce qui ne va pas."},
    )
    photos = MultipleFileField(
        label="Photos",
        required=False,
        widget=MultipleFileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
    )
    urgency = forms.ChoiceField(
        label="C'est gênant à quel point ?",
        choices=Report.Urgency.choices,
        widget=forms.RadioSelect,
        error_messages={"required": "Dites si c'est urgent."},
    )
    access = forms.ChoiceField(
        label="Accès à votre chambre",
        choices=ACCESS_CHOICES,
        widget=forms.RadioSelect,
        error_messages={"required": "Dites si l'équipe peut entrer en votre absence."},
    )

    def clean_photos(self):
        sent = self.cleaned_data.get("photos") or []
        if len(sent) > photos.MAX_PHOTOS:
            raise forms.ValidationError(f"{photos.MAX_PHOTOS} photos au plus.")
        cleaned = []
        for uploaded in sent:
            try:
                cleaned.append(photos.clean(uploaded))
            except photos.PhotoRefused as refused:
                raise forms.ValidationError(str(refused)) from refused
        return cleaned
