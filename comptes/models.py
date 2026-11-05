from django.contrib.auth.models import AbstractUser, UserManager
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from .roles import GROUPE_PAR_ROLE, PERMISSIONS, ROLES_EQUIPE, Role, definir_roles, roles_de
from .telephone import normaliser_telephone, valider_e164


class GestionnaireUtilisateurs(UserManager):
    def avec_role(self, role):
        """Les comptes qui ont ce rôle (parmi d'autres, éventuellement)."""
        return self.filter(groups__name=GROUPE_PAR_ROLE[Role(role)])

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        """Un super-utilisateur créé en ligne de commande a le rôle Administration."""
        utilisateur = super().create_superuser(username, email, password, **extra_fields)
        definir_roles(utilisateur, roles_de(utilisateur) | {Role.ADMIN})
        return utilisateur


class User(AbstractUser):
    """Utilisateur de l'application : résident ou membre de l'équipe.

    Ce modèle existe dès la première migration, comme le recommande la
    documentation de Django :
    https://docs.djangoproject.com/en/6.1/topics/auth/customizing/#using-a-custom-user-model-when-starting-a-project

    Les rôles sont les groupes de l'utilisateur ; il peut en avoir plusieurs
    (voir comptes/roles.py). Le compte appartient à la personne ; la chambre
    est portée par le séjour (carte T06).
    """

    telephone = models.CharField(
        "téléphone portable",
        max_length=16,
        blank=True,
        validators=[valider_e164],
        help_text="Saisie libre (06 12 34 56 78) ; enregistré au format international.",
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

    @property
    def roles(self):
        """Ensemble des rôles (Role) de l'utilisateur."""
        return roles_de(self)

    def a_le_role(self, role):
        return Role(role) in self.roles

    @property
    def est_equipe(self):
        """Vrai si l'utilisateur a au moins un rôle du personnel."""
        return bool(self.roles & ROLES_EQUIPE)
