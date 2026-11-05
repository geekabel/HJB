from django import forms

from housing.models import Floor

from .models import Campaign, MessageTemplate, ReplyType

TEXTAREA = {"rows": 8, "spellcheck": "true"}


class TemplateForm(forms.ModelForm):
    class Meta:
        model = MessageTemplate
        fields = ["type", "name", "title", "body", "sms_body", "reply_expected"]
        widgets = {
            "body": forms.Textarea(attrs=TEXTAREA),
            "sms_body": forms.Textarea(attrs={**TEXTAREA, "rows": 3}),
        }


class FloorChoices(forms.ModelMultipleChoiceField):
    def label_from_instance(self, floor):
        return str(floor)


class CampaignForm(forms.ModelForm):
    ask_reply = forms.BooleanField(
        label="Demander une réponse : « Présent » ou « Absent »", required=False
    )
    floors = FloorChoices(
        label="Étages",
        queryset=Floor.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    add = forms.CharField(
        label="Ajouter une chambre ou une personne",
        required=False,
        max_length=100,
        help_text="Un numéro de chambre (312) ou un nom (Awa Koné).",
    )

    class Meta:
        model = Campaign
        fields = [
            "type",
            "title",
            "body",
            "sms_body",
            "event_date",
            "start_time",
            "end_time",
            "everyone",
            "floors",
        ]
        widgets = {
            "type": forms.RadioSelect,
            "body": forms.Textarea(attrs=TEXTAREA),
            "sms_body": forms.Textarea(attrs={**TEXTAREA, "rows": 3}),
            "event_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "start_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "end_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        }
        help_texts = {
            "title": "Titre de la notification.",
            "body": (
                "Texte complet, dans l'application. Les {champs} sont remplis pour chaque personne."
            ),
            "sms_body": (
                "Pour les résidents sans l'application. Vide : le texte complet est envoyé. "
                "Les caractères hors de l'alphabet SMS (ê, ç, « ») sont remplacés."
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ask_reply"].initial = self.instance.reply_type == ReplyType.ATTENDANCE

    def save(self, commit=True):
        campaign = super().save(commit=False)
        campaign.reply_type = (
            ReplyType.ATTENDANCE if self.cleaned_data.get("ask_reply") else ReplyType.NONE
        )
        if commit:
            campaign.save()
            self.save_m2m()
        return campaign
