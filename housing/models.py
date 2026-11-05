"""Floors, rooms and stays of the residence.

The account belongs to the person; the room is carried by the stay.
A "current" stay has no departure date.

Constraints: https://docs.djangoproject.com/en/6.1/ref/models/constraints/
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Exists, F, OuterRef, Q
from django.utils import timezone


def floor_short_label(number):
    """Return "RDC", "1er", "3e": for lists."""
    if number == 0:
        return "RDC"
    return "1er" if number == 1 else f"{number}e"


class Floor(models.Model):
    number = models.PositiveSmallIntegerField(
        "numéro", unique=True, help_text="0 pour le rez-de-chaussée."
    )
    name = models.CharField("nom", max_length=60, blank=True, help_text="Facultatif.")
    visit_order = models.PositiveSmallIntegerField(
        "ordre de visite",
        default=0,
        help_text="Ordre de passage dans la rotation des visites de chambres.",
    )

    class Meta:
        verbose_name = "étage"
        verbose_name_plural = "étages"
        ordering = ["number"]

    def __str__(self):
        if self.name:
            return self.name
        if self.number == 0:
            return "Rez-de-chaussée"
        return f"{floor_short_label(self.number)} étage"

    @property
    def short_label(self):
        return floor_short_label(self.number)


class RoomQuerySet(models.QuerySet):
    def free(self):
        """Open rooms with no current stay."""
        # Exists rather than an exclude() on the relation: a room with no stay
        # at all would give an "empty" departure in the join.
        occupied = Stay.objects.filter(room=OuterRef("pk"), departure__isnull=True)
        return self.filter(active=True).exclude(Exists(occupied))


class Room(models.Model):
    number = models.CharField("numéro", max_length=10, unique=True)
    floor = models.ForeignKey(
        Floor, on_delete=models.PROTECT, related_name="rooms", verbose_name="étage"
    )
    active = models.BooleanField(
        "ouverte",
        default=True,
        help_text="Décocher pour une chambre fermée (travaux, bureau…). Elle garde son historique.",
    )

    objects = RoomQuerySet.as_manager()

    class Meta:
        verbose_name = "chambre"
        verbose_name_plural = "chambres"
        ordering = ["floor__number", "number"]

    def __str__(self):
        return f"Chambre {self.number}"

    def clean(self):
        self.number = self.number.strip().upper()


class StayQuerySet(models.QuerySet):
    def current(self):
        return self.filter(departure__isnull=True)


class Stay(models.Model):
    resident = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="stays",
        verbose_name="résident",
    )
    room = models.ForeignKey(
        Room, on_delete=models.PROTECT, related_name="stays", verbose_name="chambre"
    )
    arrival = models.DateField("arrivée", default=timezone.localdate)
    departure = models.DateField(
        "départ", null=True, blank=True, help_text="Vide si le séjour est en cours."
    )

    objects = StayQuerySet.as_manager()

    class Meta:
        verbose_name = "séjour"
        verbose_name_plural = "séjours"
        ordering = ["-arrival", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["room"],
                condition=Q(departure__isnull=True),
                name="one_current_stay_per_room",
                violation_error_code="room_occupied",
                violation_error_message="Cette chambre a déjà un séjour en cours.",
            ),
            models.UniqueConstraint(
                fields=["resident"],
                condition=Q(departure__isnull=True),
                name="one_current_stay_per_resident",
                violation_error_code="resident_already_housed",
                violation_error_message="Cette personne a déjà un séjour en cours.",
            ),
            models.CheckConstraint(
                condition=Q(departure__isnull=True) | Q(departure__gte=F("arrival")),
                name="departure_after_arrival",
                violation_error_code="departure_before_arrival",
                violation_error_message="Le départ ne peut pas précéder l'arrivée.",
            ),
        ]

    def __str__(self):
        return f"{self.resident} ({self.room})"

    @property
    def is_current(self):
        return self.departure is None

    def _overlaps(self):
        """Other stays whose dates cross these ones (same handover day allowed)."""
        others = Stay.objects.exclude(pk=self.pk).filter(
            Q(departure__isnull=True) | Q(departure__gt=self.arrival)
        )
        if self.departure is not None:
            others = others.filter(arrival__lt=self.departure)
        return others

    def clean(self):
        if self.arrival is None:
            return
        errors = {}
        crossing = self._overlaps()
        if self.is_current:
            # Two current stays: already refused by the unique constraints.
            crossing = crossing.filter(departure__isnull=False)
        if self.room_id is not None:
            if self.is_current and not self.room.active:
                errors["room"] = ValidationError("Cette chambre est fermée.", code="room_closed")
            elif crossing.filter(room_id=self.room_id).exists():
                errors["room"] = ValidationError(
                    "La chambre est occupée par quelqu'un d'autre sur ces dates.",
                    code="room_overlap",
                )
        if self.resident_id is not None and crossing.filter(resident_id=self.resident_id).exists():
            errors["resident"] = ValidationError(
                "Cette personne a un autre séjour sur ces dates.",
                code="resident_overlap",
            )
        if errors:
            raise ValidationError(errors)


WIFI_VALIDITY_DAYS = 365
# Below this many days, staff see "renew soon" in the lists (card T15).
WIFI_RENEWAL_WARNING_DAYS = 30


class WifiAccessQuerySet(models.QuerySet):
    def active(self):
        return self.filter(active=True)


class WifiAccess(models.Model):
    """Wifi username and password of a room, valid for about one year (card T15).

    The password is stored encrypted (housing/wifi_crypto.py), never in clear.
    A room has at most one active access; renewing it keeps the old one,
    inactive, for history.
    """

    class EndReason(models.TextChoices):
        RENEWED = "renewed", "Remplacé par un nouvel accès"
        DEPARTURE = "departure", "Départ du résident"
        MOVE = "move", "Changement de chambre"

    room = models.ForeignKey(
        Room, on_delete=models.PROTECT, related_name="wifi_accesses", verbose_name="chambre"
    )
    username = models.CharField("identifiant", max_length=64)
    encrypted_password = models.TextField("mot de passe chiffré", editable=False)
    generated = models.BooleanField("mot de passe généré par l'application", default=False)
    created_on = models.DateField("enregistré le", default=timezone.localdate)
    expires_on = models.DateField("expire le")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
        verbose_name="enregistré par",
    )
    active = models.BooleanField("actif", default=True)
    ended_at = models.DateTimeField("coupé le", null=True, blank=True)
    end_reason = models.CharField(
        "raison de la coupure", max_length=20, choices=EndReason.choices, blank=True
    )

    objects = WifiAccessQuerySet.as_manager()

    class Meta:
        verbose_name = "accès wifi"
        verbose_name_plural = "accès wifi"
        ordering = ["-created_on", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["room"],
                condition=Q(active=True),
                name="one_active_wifi_per_room",
                violation_error_message="Cette chambre a déjà un accès wifi actif.",
            ),
            models.CheckConstraint(
                condition=Q(expires_on__gt=F("created_on")),
                name="wifi_expires_after_creation",
                violation_error_message="L'expiration doit suivre la date d'enregistrement.",
            ),
        ]

    def __str__(self):
        return f"Wifi de la chambre {self.room.number}"

    @property
    def days_left(self):
        return (self.expires_on - timezone.localdate()).days

    @property
    def is_expired(self):
        return self.days_left < 0

    @property
    def renew_soon(self):
        return 0 <= self.days_left <= WIFI_RENEWAL_WARNING_DAYS
