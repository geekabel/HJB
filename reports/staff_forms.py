"""Forms of the staff on a report (card T31)."""

from datetime import datetime, time, timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone


def handlers():
    """Active staff who can handle reports (role Accueil, Maintenance, Administration)."""
    return (
        get_user_model()
        .objects.filter(is_active=True, groups__permissions__codename="manage_reports")
        .distinct()
        .order_by("first_name", "last_name", "username")
    )


class PersonChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, person):
        return person.get_full_name() or person.get_username()


class AssignForm(forms.Form):
    assignee = PersonChoiceField(label="Confié à", queryset=handlers(), empty_label=None)

    def __init__(self, *args, current=None, **kwargs):
        super().__init__(*args, **kwargs)
        # The person it is given to stays in the list, even if they lost the
        # right since: the list never shows someone else by mistake.
        query = handlers()
        if current is not None:
            query = (
                get_user_model()
                .objects.filter(
                    Q(is_active=True, groups__permissions__codename="manage_reports")
                    | Q(pk=current)
                )
                .distinct()
                .order_by("first_name", "last_name", "username")
            )
        self.fields["assignee"].queryset = query


class PlanForm(forms.Form):
    day = forms.DateField(
        label="Jour",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    start = forms.TimeField(
        label="De", widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M")
    )
    end = forms.TimeField(label="À", widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))
    note = forms.CharField(
        label="Mot pour le résident",
        required=False,
        max_length=300,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Par exemple : «\u00a0Merci de libérer l'accès au radiateur.\u00a0»",
    )

    def clean_day(self):
        day = self.cleaned_data["day"]
        if day < timezone.localdate():
            raise forms.ValidationError("Choisissez aujourd'hui ou un jour à venir.")
        return day

    def clean(self):
        data = super().clean()
        day, start, end = data.get("day"), data.get("start"), data.get("end")
        if start and end and end <= start:
            self.add_error("end", "L'heure de fin doit être après le début.")
        now = timezone.localtime()
        if day == now.date() and start and start <= now.time():
            self.add_error("start", "Cette heure est passée.")
        return data

    def moments(self):
        day = self.cleaned_data["day"]
        return tuple(
            timezone.make_aware(datetime.combine(day, self.cleaned_data[key]))
            for key in ("start", "end")
        )


class DoneForm(forms.Form):
    note = forms.CharField(
        label="Ce qui a été fait",
        required=False,
        max_length=300,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Lu par le résident. Facultatif.",
    )


def initial_plan(report):
    """The planned visit, or tomorrow 9:00 to 10:00."""
    if report.intervention_start:
        start = timezone.localtime(report.intervention_start)
        end = timezone.localtime(report.intervention_end)
        return {"day": start.date(), "start": start.time(), "end": end.time()}
    tomorrow = timezone.localdate() + timedelta(days=1)
    return {"day": tomorrow, "start": time(9), "end": time(10)}
