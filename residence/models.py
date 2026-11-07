"""Settings of the residence, changed by the administration (card T37b).

Only what is not a secret lives here: the keys of the SMS providers, the
VAPID key, the SECRET_KEY and the wifi keys stay in the server's
environment. If the database, a backup or an administrator account
leaks, they stay safe; and a typo in a form cannot cut every sending.

A single row (pk=1), read with ResidenceSettings.load(). Each change is
written in the audit log (residence/views.py).
"""

from django.core.exceptions import ValidationError
from django.core.validators import (
    MaxValueValidator,
    MinValueValidator,
    RegexValidator,
    validate_email,
)
from django.db import models


def _days(label, default, low, high, help_text):
    return models.PositiveSmallIntegerField(
        label,
        default=default,
        validators=[MinValueValidator(low), MaxValueValidator(high)],
        help_text=f"{help_text} De {low} à {high} jours.",
    )


class SmsChoice(models.TextChoices):
    SERVER = "", "Celui du serveur"
    OVH = "ovh", "OVHcloud"
    SMSGATE = "smsgate", "SMSGate (téléphone de la résidence)"
    PAUSED = "paused", "Aucun : SMS coupés"


class ResidenceSettings(models.Model):
    organization_name = models.CharField(
        "nom de l'association", max_length=100, default="Habitat Jeunes Belfort"
    )
    organization_address = models.TextField(
        "adresse de l'association",
        max_length=300,
        blank=True,
        help_text="Affichée sur la page «\u00a0Vos données\u00a0».",
    )
    privacy_contact = models.CharField(
        "contact pour les données personnelles",
        max_length=200,
        blank=True,
        help_text=(
            "Une adresse e-mail, ou quelques mots. "
            "Vide\u00a0: «\u00a0l'accueil de la résidence\u00a0»."
        ),
    )
    emergency_phone = models.CharField(
        "numéro d'urgence",
        max_length=20,
        blank=True,
        validators=[
            RegexValidator(
                r"^\+?[0-9][0-9 .]{5,18}$",
                "Chiffres, espaces et points seulement, par exemple 03 84 00 00 00.",
            )
        ],
        help_text=(
            "Montré aux résidents pour un problème grave. "
            "Vide\u00a0: «\u00a0appelez l'accueil\u00a0»."
        ),
    )
    sms_provider = models.CharField(
        "service SMS",
        max_length=10,
        choices=SmsChoice.choices,
        blank=True,
        default=SmsChoice.SERVER,
        help_text="Ses clés restent sur le serveur : seuls les services prêts sont proposés.",
    )
    summary_hour = models.PositiveSmallIntegerField(
        "heure du récapitulatif des signalements",
        default=9,
        validators=[MinValueValidator(7), MaxValueValidator(11)],
        help_text="Du lundi au vendredi. De 7 h à 11 h.",
    )

    # Retention (privacy/retention.py). The bounds keep the page "Vos
    # données" honest: the journal stays between 6 months and 1 year (CNIL).
    former_residents_days = _days(
        "compte d'un ancien résident", 365, 180, 1095, "Après le dernier départ."
    )
    report_photos_days = _days(
        "photos d'un signalement", 180, 30, 730, "Après la clôture du signalement."
    )
    meetings_days = _days("rendez-vous et leur motif", 365, 90, 1095, "Après le rendez-vous.")
    direct_messages_days = _days("messages avec un éducateur", 365, 90, 1095, "Après l'envoi.")
    deliveries_days = _days(
        "destinataires d'un message et réponses", 365, 90, 1095, "Après l'envoi."
    )
    wifi_accesses_days = _days("anciens accès wifi", 365, 90, 1095, "Après la fin de l'accès.")
    audit_log_days = _days(
        "journal des actions sensibles", 365, 180, 365, "La CNIL recommande de 6 mois à 1 an."
    )
    codes_days = _days("codes d'activation et de vérification", 30, 7, 90, "Après leur fin.")

    updated_at = models.DateTimeField("modifié le", auto_now=True)

    class Meta:
        verbose_name = "réglages de la résidence"
        verbose_name_plural = "réglages de la résidence"

    def __str__(self):
        return "Réglages de la résidence"

    def save(self, *args, **kwargs):
        self.pk = 1  # a single row
        super().save(*args, **kwargs)

    def clean(self):
        contact = self.privacy_contact.strip()
        if "@" in contact:
            try:
                validate_email(contact)
            except ValidationError:
                raise ValidationError(
                    {"privacy_contact": "Cette adresse e-mail n'est pas valide."}
                ) from None

    @classmethod
    def load(cls):
        row, _ = cls.objects.get_or_create(pk=1)
        return row

    def retention_days(self, key):
        return getattr(self, f"{key}_days")
