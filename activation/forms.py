from django import forms


class ActivationCodeForm(forms.Form):
    code = forms.CharField(
        label="Code d'activation",
        max_length=20,
        help_text="10 lettres et chiffres, par exemple ABCDE-FGHJK. Remis par l'accueil.",
        widget=forms.TextInput(
            attrs={
                "autocomplete": "off",
                "autocapitalize": "characters",
                "spellcheck": "false",
                "class": "code-field",
            }
        ),
    )


class SmsCodeForm(forms.Form):
    code = forms.CharField(
        label="Code reçu par SMS",
        max_length=12,
        help_text="6 chiffres.",
        widget=forms.TextInput(
            attrs={
                "autocomplete": "one-time-code",
                "inputmode": "numeric",
                "class": "code-field",
            }
        ),
    )


class AppCodeForm(forms.Form):
    code = forms.CharField(
        label="Code affiché dans l'application",
        max_length=12,
        help_text="6 chiffres. Il change toutes les 30 secondes.",
        widget=forms.TextInput(
            attrs={
                "autocomplete": "one-time-code",
                "inputmode": "numeric",
                "class": "code-field",
            }
        ),
    )
