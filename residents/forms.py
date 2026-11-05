"""Formulaire de la fiche d'un résident (création et modification)."""

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify

from comptes.models import User
from logement.models import Chambre
from logement.services import affecter_chambre, sejour_en_cours

SANS_SAISIE_AUTO = {"autocomplete": "off"}


class ChoixChambre(forms.ModelChoiceField):
    def label_from_instance(self, chambre):
        return f"{chambre.numero} · {chambre.etage}"


def nom_utilisateur_libre(prenom, nom):
    """« awa.kone », puis « awa.kone-2 »… Les résidents ne s'en servent pas pour se connecter."""
    base = ".".join(p for p in (slugify(prenom), slugify(nom)) if p) or "resident"
    base = base[:140]
    candidat, n = base, 1
    while User.objects.filter(username=candidat).exists():
        n += 1
        candidat = f"{base}-{n}"
    return candidat


class FormulaireResident(forms.ModelForm):
    # Saisie libre (espaces, +33…) : le modèle la ramène au format international.
    telephone = forms.CharField(
        label="Téléphone portable",
        max_length=30,
        required=False,
        help_text="Par exemple 06 12 34 56 78. Il sert à envoyer les SMS et le code d'activation.",
        widget=forms.TextInput(attrs={"type": "tel", "inputmode": "tel", **SANS_SAISIE_AUTO}),
    )
    chambre = ChoixChambre(
        queryset=Chambre.objects.none(),
        required=False,
        empty_label="Pas encore de chambre",
        label="Chambre",
    )
    arrivee = forms.DateField(
        label="Date d'arrivée",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )

    class Meta:
        model = User
        fields = ["first_name", "last_name", "telephone", "email"]
        labels = {"first_name": "Prénom", "last_name": "Nom", "email": "Adresse e-mail"}
        widgets = {
            "first_name": forms.TextInput(attrs=SANS_SAISIE_AUTO),
            "last_name": forms.TextInput(attrs=SANS_SAISIE_AUTO),
            "email": forms.EmailInput(attrs=SANS_SAISIE_AUTO),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True
        # Obligatoire dès qu'une chambre est choisie (voir clean) : pas de mention « facultatif ».
        self.fields["arrivee"].masquer_facultatif = True
        if self.instance.telephone:
            self.initial["telephone"] = self.instance.telephone_affiche
        self.sejour = sejour_en_cours(self.instance) if self.instance.pk else None
        proposees = Q(pk__in=Chambre.objects.libres())
        if self.sejour:
            proposees |= Q(pk=self.sejour.chambre_id)
            champ = self.fields["chambre"]
            champ.required = True
            champ.empty_label = None
            champ.help_text = (
                "Pour un déménagement dans la résidence, choisissez la nouvelle chambre "
                "et mettez la date du changement."
            )
            self.initial.setdefault("chambre", self.sejour.chambre_id)
            self.initial.setdefault("arrivee", self.sejour.arrivee)
        else:
            self.initial.setdefault("arrivee", timezone.localdate())
        self.fields["chambre"].queryset = Chambre.objects.filter(proposees).select_related("etage")
        if self.instance.pk and not self.instance.is_active and not self.sejour:
            # Ancien résident : on garde son identité à jour, sans le reloger ici.
            del self.fields["chambre"]
            del self.fields["arrivee"]

    def clean(self):
        donnees = super().clean()
        chambre, arrivee = donnees.get("chambre"), donnees.get("arrivee")
        if chambre and not arrivee:
            self.add_error("arrivee", "Indiquez la date d'arrivée dans la chambre.")
        elif (
            self.sejour
            and chambre
            and chambre.pk != self.sejour.chambre_id
            and arrivee <= self.sejour.arrivee
            # Le jour même de l'arrivée, changer de chambre corrige une erreur de saisie.
            and not arrivee == self.sejour.arrivee == timezone.localdate()
        ):
            # Sinon, garder la date du séjour en cours effacerait l'ancienne chambre
            # de l'historique au lieu d'enregistrer un déménagement.
            self.add_error(
                "arrivee",
                "Pour un déménagement, indiquez sa date : après le "
                f"{self.sejour.arrivee:%d/%m/%Y}, jour d'arrivée dans la chambre actuelle.",
            )
        return donnees

    def enregistrer(self):
        """Enregistre le compte puis le séjour. À appeler dans une transaction.

        Lève ValidationError si le séjour est refusé (chambre prise entre-temps…).
        """
        resident = self.save(commit=False)
        if resident.pk is None:
            resident.username = nom_utilisateur_libre(resident.first_name, resident.last_name)
            # Les résidents se connectent par clé d'accès, jamais par mot de passe.
            resident.set_unusable_password()
            resident.save()
        else:
            # Verrou sur la ligne : un départ enregistré au même moment passe avant
            # ou après, jamais au milieu. On n'écrit que les champs du formulaire,
            # pour ne pas rétablir un compte désactivé entre-temps.
            en_base = User.objects.select_for_update().get(pk=resident.pk)
            if "chambre" in self.fields and not en_base.is_active:
                raise ValidationError(
                    "Le départ de cette personne vient d'être enregistré. Rechargez la fiche."
                )
            resident.save(update_fields=list(self._meta.fields))
        chambre, arrivee = self.cleaned_data.get("chambre"), self.cleaned_data.get("arrivee")
        if chambre is None:
            return resident
        if self.sejour and self.sejour.chambre_id == chambre.pk:
            if arrivee != self.sejour.arrivee:
                self.sejour.arrivee = arrivee
                self.sejour.full_clean()
                self.sejour.save()
        else:
            affecter_chambre(resident, chambre, arrivee)
        return resident

    def ajouter_erreurs_sejour(self, erreur: ValidationError):
        for champ, messages in erreur.message_dict.items():
            self.add_error(champ if champ in ("chambre", "arrivee") else None, messages)


class FormulaireImport(forms.Form):
    fichier = forms.FileField(
        label="Fichier CSV ou Excel",
        help_text="Format .csv ou .xlsx, 2 Mo au plus, 500 résidents au plus.",
        widget=forms.FileInput(attrs={"accept": ".csv,.xlsx"}),
    )


class FormulaireDepart(forms.Form):
    depart = forms.DateField(
        label="Date du départ",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )

    def __init__(self, *args, sejour=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.sejour = sejour
        aujourd_hui = timezone.localdate()
        self.fields["depart"].initial = aujourd_hui
        self.fields["depart"].widget.attrs["max"] = aujourd_hui.isoformat()
        if sejour:
            self.fields["depart"].widget.attrs["min"] = sejour.arrivee.isoformat()

    def clean_depart(self):
        from .depart import verifier_date

        le = self.cleaned_data["depart"]
        verifier_date(le, self.sejour)
        return le
