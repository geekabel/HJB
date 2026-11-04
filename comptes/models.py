from django.contrib.auth.models import AbstractUser, UserManager
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from .roles import PERMISSIONS, Role, synchroniser_groupes
from .telephone import normaliser_telephone, valider_e164


class GestionnaireUtilisateurs(UserManager):
    """Un super-utilisateur créé en ligne de commande a le rôle Administration."""

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("role", Role.ADMIN)
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    """Utilisateur de l'application : résident ou membre de l'équipe.

    Ce modèle existe dès la première migration, comme le recommande la
    documentation de Django :
    https://docs.djangoproject.com/en/6.1/topics/auth/customizing/#using-a-custom-user-model-when-starting-a-project

    Le compte appartient à la personne ; la chambre est portée par le séjour (carte T06).
    """

    role = models.CharField(
        "rôle", max_length=12, choices=Role.choices, default=Role.RESIDENT, db_index=True
    )
    telephone = models.CharField(
        "téléphone portable",
        max_length=16,
        blank=True,
        validators=[valider_e164],
        help_text="Saisie libre (06 12 34 56 78) ; enregistré au format international.",
    )
    est_moderateur = models.BooleanField(
        "modérateur de la discussion",
        default=False,
        help_text="Donné par l'équipe à un membre du personnel ou à un résident.",
    )

    objects = GestionnaireUtilisateurs()

    class Meta(AbstractUser.Meta):
        verbose_name = "utilisateur"
        verbose_name_plural = "utilisateurs"
        permissions = list(PERMISSIONS.items())
        constraints = [
            # Un numéro sert à une seule personne ; plusieurs comptes peuvent ne pas en avoir.
            models.UniqueConstraint(
                fields=["telephone"],
                condition=~Q(telephone=""),
                name="telephone_unique_si_renseigne",
                violation_error_message="Ce numéro est déjà utilisé par une autre personne.",
            ),
        ]

    def clean_fields(self, exclude=None):
        # Normaliser la saisie avant les validateurs de champ (dont E.164),
        # car full_clean() appelle clean_fields() avant clean().
        erreurs = {}
        exclude = set(exclude or ())
        if "telephone" not in exclude:
            try:
                self.telephone = normaliser_telephone(self.telephone)
            except ValidationError as erreur:
                erreurs["telephone"] = erreur.error_list
                exclude.add("telephone")
        try:
            super().clean_fields(exclude=exclude)
        except ValidationError as erreur:
            erreurs.update(erreur.error_dict)
        if erreurs:
            raise ValidationError(erreurs)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        champs = kwargs.get("update_fields")
        if champs is None or {"role", "est_moderateur"} & set(champs):
            synchroniser_groupes(self)

    @property
    def est_equipe(self):
        """Vrai pour tout membre du personnel, quel que soit son rôle."""
        return self.role != Role.RESIDENT
