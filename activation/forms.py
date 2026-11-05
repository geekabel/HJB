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
