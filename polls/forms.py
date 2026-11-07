from django import forms
from django.utils import timezone

from .services import MAX_OPTIONS, MIN_OPTIONS, clean_labels


class PollForm(forms.Form):
    """Poll part of the composer, for a message of type "Vote, avis" (card T25)."""

    options = forms.CharField(
        label="Choix proposés",
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text=(f"Un choix par ligne, de {MIN_OPTIONS} à {MAX_OPTIONS}."),
    )
    closes_at = forms.DateTimeField(
        label="Clôture du vote",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        help_text="Les résultats s'affichent après cette heure.",
    )
    allow_comment = forms.BooleanField(
        label="Permettre un commentaire pour l'équipe", required=False, initial=True
    )

    def __init__(self, *args, poll=None, partial=False, **kwargs):
        if poll is not None and "initial" not in kwargs:
            kwargs["initial"] = {
                "options": "\n".join(option.label for option in poll.options.all()),
                "closes_at": poll.closes_at and timezone.localtime(poll.closes_at),
                "allow_comment": poll.allow_comment,
            }
        kwargs.setdefault("prefix", "poll")
        super().__init__(*args, **kwargs)
        # A draft can stay incomplete: the check before sending lists what
        # is missing (messaging.sending.problems). The labels stay "required".
        self.partial = partial
        if partial:
            for field in self.fields.values():
                field.required = False

    def clean_options(self):
        labels = clean_labels(self.cleaned_data["options"].splitlines())
        if len(labels) > MAX_OPTIONS:
            raise forms.ValidationError(f"{MAX_OPTIONS} choix au plus.")
        if len(labels) < MIN_OPTIONS and not self.partial:
            raise forms.ValidationError(f"Proposez au moins {MIN_OPTIONS} choix différents.")
        return labels
