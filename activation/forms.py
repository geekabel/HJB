from django import forms


class FormulaireCode(forms.Form):
    code = forms.CharField(
        label="Code d'activation",
        max_length=20,
        help_text="10 lettres et chiffres, par exemple ABCDE-FGHJK. Remis par l'accueil.",
        widget=forms.TextInput(
            attrs={
                "autocomplete": "off",
                "autocapitalize": "characters",
                "spellcheck": "false",
                "class": "champ-code",
            }
        ),
    )


class FormulaireCodeSms(forms.Form):
    code = forms.CharField(
        label="Code reçu par SMS",
        max_length=12,
        help_text="6 chiffres.",
        widget=forms.TextInput(
            attrs={
                "autocomplete": "one-time-code",
                "inputmode": "numeric",
                "class": "champ-code",
            }
        ),
    )
