from django.contrib.auth.models import AbstractUser, UserManager
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .phone import display_phone, mask_phone, normalize_phone, validate_e164
from .roles import GROUP_BY_ROLE, PERMISSIONS, STAFF_ROLES, Role, roles_of, set_roles


class AccountState(models.TextChoices):
    """Account state as seen by the staff. Card T11 will add the invitation and its expiry."""

    ACTIVE = "active", "Activé"
    PENDING = "pending", "Pas encore activé"
    DISABLED = "disabled", "Désactivé"


ACCOUNT_STATE_FILTERS = {
    AccountState.ACTIVE: Q(is_active=True, last_login__isnull=False),
    AccountState.PENDING: Q(is_active=True, last_login__isnull=True),
    AccountState.DISABLED: Q(is_active=False),
}


class HJBUserManager(UserManager):
    def residents(self):
        """Accounts with no staff role (a resident moderator is one of them).

        An account with access to the admin site (is_staff, is_superuser) is
        never a resident, even without a group.
        """
        return self.exclude(groups__name__in=[GROUP_BY_ROLE[r] for r in STAFF_ROLES]).filter(
            is_staff=False, is_superuser=False
        )

    def with_role(self, role):
        """Accounts that have this role (possibly among others)."""
        return self.filter(groups__name=GROUP_BY_ROLE[Role(role)])

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        """A superuser created from the command line gets the Administration role."""
        user = super().create_superuser(username, email, password, **extra_fields)
        set_roles(user, roles_of(user) | {Role.ADMIN})
        return user


class User(AbstractUser):
    """Application user: a resident or a staff member.

    This model exists from the first migration, as the Django
    documentation recommends:
    https://docs.djangoproject.com/en/6.1/topics/auth/customizing/#using-a-custom-user-model-when-starting-a-project

    Roles are the user's groups. A user can have several of them
    (see accounts/roles.py). The account belongs to the person. The room
    belongs to the stay (card T06).
    """

    phone = models.CharField(
        "téléphone portable",
        max_length=16,
        blank=True,
        validators=[validate_e164],
        help_text="Saisie libre (06 12 34 56 78) ; enregistré au format international.",
    )
    verified_phone = models.CharField(
        "numéro vérifié",
        max_length=16,
        blank=True,
        help_text="Confirmé par code SMS. S'il diffère du numéro actuel, rien n'est vérifié.",
    )
    phone_verified_at = models.DateTimeField("téléphone vérifié le", null=True, blank=True)
    wifi_expiry_reminder = models.BooleanField(
        "rappel avant la fin de l'accès wifi",
        default=True,
        help_text="Notification 15 jours avant la fin de l'accès wifi de la chambre (carte T17).",
    )

    objects = HJBUserManager()

    class Meta(AbstractUser.Meta):
        verbose_name = "utilisateur"
        verbose_name_plural = "utilisateurs"
        permissions = list(PERMISSIONS.items())
        constraints = [
            # A number belongs to one person only. Several accounts may have none.
            models.UniqueConstraint(
                fields=["phone"],
                condition=~Q(phone=""),
                name="phone_unique_if_set",
                violation_error_message="Ce numéro est déjà utilisé par une autre personne.",
            ),
        ]

    def clean_fields(self, exclude=None):
        # Normalize the input before the field validators (including E.164),
        # because full_clean() calls clean_fields() before clean().
        errors = {}
        exclude = set(exclude or ())
        if "phone" not in exclude:
            try:
                self.phone = normalize_phone(self.phone)
            except ValidationError as error:
                errors["phone"] = error.error_list
                exclude.add("phone")
        try:
            super().clean_fields(exclude=exclude)
        except ValidationError as error:
            errors.update(error.error_dict)
        if errors:
            raise ValidationError(errors)

    @property
    def roles(self):
        """Set of the user's roles (Role)."""
        return roles_of(self)

    def has_role(self, role):
        return Role(role) in self.roles

    @property
    def roles_label(self):
        """Roles in plain words, for example "Accueil, Maintenance"."""
        return ", ".join(sorted(r.label for r in self.roles)) or "Résident"

    @property
    def account_state(self):
        # An account is active from the first login (login() fills last_login).
        if not self.is_active:
            return AccountState.DISABLED
        return AccountState.ACTIVE if self.last_login else AccountState.PENDING

    @property
    def phone_is_verified(self):
        """True only if the current number is the one that was verified.

        We compare the numbers instead of tracking changes: the rule
        holds whatever the way the number changes (profile page,
        admin site, import, update() in the database).
        """
        return bool(self.phone and self.phone_verified_at and self.verified_phone == self.phone)

    @property
    def phone_display(self):
        return display_phone(self.phone)

    @property
    def phone_masked(self):
        return mask_phone(self.phone)

    @property
    def has_staff_role(self):
        """True if the user has at least one staff role."""
        return bool(self.roles & STAFF_ROLES)


class ActivationCodeQuerySet(models.QuerySet):
    def valid(self):
        """Not used, not cancelled, not expired."""
        return self.filter(
            used_at__isnull=True, cancelled_at__isnull=True, expires_at__gt=timezone.now()
        )


class ActivationCode(models.Model):
    """Code given at the front desk to activate an account (card T11).

    The code is never stored in clear: only its HMAC digest is
    (see accounts/activation_codes.py). It works only once and expires after 72 h.
    """

    user = models.ForeignKey(
        "User",
        on_delete=models.CASCADE,
        related_name="activation_codes",
        verbose_name="utilisateur",
    )
    digest = models.CharField("empreinte", max_length=64, unique=True, editable=False)
    created_by = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, related_name="+", verbose_name="créé par"
    )
    created_at = models.DateTimeField("créé le", auto_now_add=True)
    expires_at = models.DateTimeField("expire le")
    used_at = models.DateTimeField("utilisé le", null=True, blank=True)
    cancelled_at = models.DateTimeField(
        "annulé le", null=True, blank=True, help_text="Remplacé par un code plus récent."
    )
    for_staff = models.BooleanField(
        "pour le personnel",
        default=False,
        help_text="Remis par un administrateur à un membre du personnel (carte T14).",
    )

    objects = ActivationCodeQuerySet.as_manager()

    class Meta:
        verbose_name = "code d'activation"
        verbose_name_plural = "codes d'activation"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Code pour {self.user} ({self.created_at:%d/%m/%Y})"


class ActivationFailure(models.Model):
    """Entry of an unknown activation code: used to limit attempts per address."""

    ip_address = models.GenericIPAddressField("adresse IP", null=True)
    created_at = models.DateTimeField("créé le", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "échec d'activation"
        verbose_name_plural = "échecs d'activation"

    def __str__(self):
        return f"Échec depuis {self.ip_address or '?'} ({self.created_at:%d/%m/%Y %H:%M})"


class PhoneVerification(models.Model):
    """6-digit SMS code sent during activation (card T12).

    Only the HMAC digest of the code is kept. Valid for 10 minutes, 5 attempts.
    """

    user = models.ForeignKey(
        "User",
        on_delete=models.CASCADE,
        related_name="phone_verifications",
        verbose_name="utilisateur",
    )
    phone = models.CharField("numéro", max_length=16)
    digest = models.CharField("empreinte", max_length=64, editable=False)
    created_at = models.DateTimeField("envoyé le", auto_now_add=True, db_index=True)
    expires_at = models.DateTimeField("expire le")
    attempts = models.PositiveSmallIntegerField("tentatives", default=0)
    verified_at = models.DateTimeField("vérifié le", null=True, blank=True)

    class Meta:
        verbose_name = "vérification de téléphone"
        verbose_name_plural = "vérifications de téléphone"
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"Vérification pour {self.user} ({self.created_at:%d/%m/%Y %H:%M})"
