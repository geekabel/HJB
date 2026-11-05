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
    when = forms.ChoiceField(
        label="Quand ?",
        choices=[("now", "Maintenant"), ("later", "Programmer")],
        initial="now",
        required=False,  # nothing chosen: now
        widget=forms.RadioSelect,
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
            "send_at",
            "remind",
        ]
        widgets = {
            "type": forms.RadioSelect,
            "body": forms.Textarea(attrs=TEXTAREA),
            "sms_body": forms.Textarea(attrs={**TEXTAREA, "rows": 3}),
            "event_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "start_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "end_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "send_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
        }
        labels = {
            "send_at": "Date et heure de l'envoi",
            "remind": "Relancer le jour J à 8 h ceux qui n'ont pas répondu",
        }
        help_texts = {
            "title": "Titre de la notification.",
            "body": (
                "Texte complet, dans l'application. Les {champs} sont remplis pour chaque personne."
            ),
            "sms_body": (
                "Pour les résidents sans l'application. Vide : le texte complet est envoyé. "
                "Les caractères hors de l'alphabet SMS (ê, ç, guillemets) sont remplacés."
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ask_reply"].initial = self.instance.reply_type == ReplyType.ATTENDANCE
        self.fields["when"].initial = "later" if self.instance.send_at else "now"

    def clean(self):
        data = super().clean()
        if data.get("when") == "later" and not data.get("send_at"):
            self.add_error("send_at", "Indiquez la date et l'heure de l'envoi.")
        if data.get("when") != "later":
            data["send_at"] = None
        if data.get("remind") and not data.get("ask_reply"):
            self.add_error("remind", "La relance demande une réponse « Présent » ou « Absent ».")
        return data

    def save(self, commit=True):
        campaign = super().save(commit=False)
        campaign.reply_type = (
            ReplyType.ATTENDANCE if self.cleaned_data.get("ask_reply") else ReplyType.NONE
        )
        campaign.send_at = self.cleaned_data.get("send_at")
        if commit:
            campaign.save()
            self.save_m2m()
        return campaign
