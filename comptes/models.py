from django.contrib.auth.models import AbstractUser, UserManager
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .roles import GROUPE_PAR_ROLE, PERMISSIONS, ROLES_EQUIPE, Role, definir_roles, roles_de
from .telephone import afficher_telephone, masquer_telephone, normaliser_telephone, valider_e164


class EtatCompte(models.TextChoices):
    """État du compte vu par l'équipe. La carte T11 ajoutera l'invitation et son expiration."""

    ACTIVE = "active", "Activé"
    EN_ATTENTE = "en_attente", "Pas encore activé"
    DESACTIVE = "desactive", "Désactivé"


FILTRE_ETAT_COMPTE = {
    EtatCompte.ACTIVE: Q(is_active=True, last_login__isnull=False),
    EtatCompte.EN_ATTENTE: Q(is_active=True, last_login__isnull=True),
    EtatCompte.DESACTIVE: Q(is_active=False),
}


class GestionnaireUtilisateurs(UserManager):
    def residents(self):
        """Comptes sans rôle du personnel (un résident modérateur en fait partie).

        Un compte qui a accès à l'administration (is_staff, is_superuser) n'est
        jamais un résident, même sans groupe.
        """
        return self.exclude(groups__name__in=[GROUPE_PAR_ROLE[r] for r in ROLES_EQUIPE]).filter(
            is_staff=False, is_superuser=False
        )

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
    def libelle_roles(self):
        """Les rôles en clair, par exemple « Accueil, Maintenance »."""
        return ", ".join(sorted(r.label for r in self.roles)) or "Résident"

    @property
    def etat_compte(self):
        # Un compte est activé dès la première connexion (login() remplit last_login).
        if not self.is_active:
            return EtatCompte.DESACTIVE
        return EtatCompte.ACTIVE if self.last_login else EtatCompte.EN_ATTENTE

    @property
    def telephone_affiche(self):
        return afficher_telephone(self.telephone)

    @property
    def telephone_masque(self):
        return masquer_telephone(self.telephone)

    @property
    def est_equipe(self):
        """Vrai si l'utilisateur a au moins un rôle du personnel."""
        return bool(self.roles & ROLES_EQUIPE)


class CodeActivationQuerySet(models.QuerySet):
    def valides(self):
        """Ni utilisés, ni annulés, ni expirés."""
        return self.filter(
            utilise_le__isnull=True, annule_le__isnull=True, expire_le__gt=timezone.now()
        )


class CodeActivation(models.Model):
    """Code remis à l'accueil pour activer un compte (carte T11).

    Le code n'est jamais stocké en clair : seule son empreinte HMAC l'est
    (voir comptes/activation.py). Il ne sert qu'une fois et expire après 72 h.
    """

    utilisateur = models.ForeignKey(
        "User", on_delete=models.CASCADE, related_name="codes_activation"
    )
    empreinte = models.CharField(max_length=64, unique=True, editable=False)
    cree_par = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, related_name="+", verbose_name="créé par"
    )
    cree_le = models.DateTimeField("créé le", auto_now_add=True)
    expire_le = models.DateTimeField("expire le")
    utilise_le = models.DateTimeField("utilisé le", null=True, blank=True)
    annule_le = models.DateTimeField(
        "annulé le", null=True, blank=True, help_text="Remplacé par un code plus récent."
    )

    objects = CodeActivationQuerySet.as_manager()

    class Meta:
        verbose_name = "code d'activation"
        verbose_name_plural = "codes d'activation"
        ordering = ["-cree_le"]

    def __str__(self):
        return f"Code pour {self.utilisateur} ({self.cree_le:%d/%m/%Y})"


class EchecActivation(models.Model):
    """Saisie d'un code d'activation inconnu : sert à limiter les essais par adresse."""

    adresse_ip = models.GenericIPAddressField(null=True)
    cree_le = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "échec d'activation"
        verbose_name_plural = "échecs d'activation"

    def __str__(self):
        return f"Échec depuis {self.adresse_ip or '?'} ({self.cree_le:%d/%m/%Y %H:%M})"
