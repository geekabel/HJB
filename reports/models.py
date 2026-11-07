"""Reports of a problem in a room (cards T30 to T33).

A resident reports a problem (T30); the staff handle it on a board (T31) within
a delay set by the urgency (T32); the resident follows it and confirms it is
fixed (T33). Each step is a ReportEvent: the history of the report.
"""

import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.formats import date_format


class Report(models.Model):
    class Category(models.TextChoices):
        ELECTRICITY = "electricity", "Électricité"
        PLUMBING = "plumbing", "Plomberie"
        PESTS = "pests", "Nuisibles"
        FURNITURE = "furniture", "Mobilier"
        HEATING = "heating", "Chauffage"
        OTHER = "other", "Autre"

    class Urgency(models.TextChoices):
        CAN_WAIT = "can_wait", "Peut attendre"
        ANNOYING = "annoying", "Gênant"
        URGENT = "urgent", "Urgent"

    class Status(models.TextChoices):
        NEW = "new", "Nouveau"
        ACKNOWLEDGED = "acknowledged", "Pris en charge"
        SCHEDULED = "scheduled", "Planifié"
        DONE = "done", "Fait"
        CLOSED = "closed", "Clos"

    ICONS = {
        Category.ELECTRICITY: "bolt",
        Category.PLUMBING: "drop",
        Category.PESTS: "bug",
        Category.FURNITURE: "sofa",
        Category.HEATING: "thermometer",
        Category.OTHER: "more",
    }

    # Time to take a report in hand, by urgency (data model, docs/modele-de-donnees.md).
    DELAYS = {
        Urgency.URGENT: timedelta(hours=4),
        Urgency.ANNOYING: timedelta(hours=48),
        Urgency.CAN_WAIT: timedelta(days=7),
    }

    resident = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reports",
        verbose_name="résident",
    )
    room = models.ForeignKey(
        "housing.Room", on_delete=models.PROTECT, related_name="reports", verbose_name="chambre"
    )
    category = models.CharField("catégorie", max_length=20, choices=Category.choices)
    description = models.TextField("description", max_length=1000)
    urgency = models.CharField("urgence", max_length=10, choices=Urgency.choices)
    access_allowed = models.BooleanField("entrée permise en l'absence du résident", default=False)
    status = models.CharField("état", max_length=20, choices=Status.choices, default=Status.NEW)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_reports",
        verbose_name="confié à",
    )
    due_at = models.DateTimeField("à traiter avant")
    intervention_start = models.DateTimeField("début de l'intervention", null=True, blank=True)
    intervention_end = models.DateTimeField("fin de l'intervention", null=True, blank=True)
    created_at = models.DateTimeField("créé le", default=timezone.now)
    updated_at = models.DateTimeField("mis à jour le", auto_now=True)

    class Meta:
        verbose_name = "signalement"
        verbose_name_plural = "signalements"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "due_at"])]

    def __str__(self):
        return f"Signalement n° {self.pk} · {self.get_category_display()}"

    @classmethod
    def due_for(cls, urgency, start):
        return start + cls.DELAYS[urgency]

    @property
    def icon(self):
        return self.ICONS.get(self.category, "tool")

    @property
    def is_open(self):
        return self.status != self.Status.CLOSED

    # Still to handle: a report is late when its due date passed before an
    # intervention was planned or done (card T31; reminders in T32).
    WAITING = (Status.NEW, Status.ACKNOWLEDGED)

    def visit_text(self):
        """'vendredi 10 novembre, de 10:00 à 12:00' (the planned visit)."""
        if not self.intervention_start:
            return ""
        start = timezone.localtime(self.intervention_start)
        end = timezone.localtime(self.intervention_end)
        return f"{date_format(start, 'l j F')}, de {start:%H:%M} à {end:%H:%M}"

    def is_late(self, now=None):
        return self.status in self.WAITING and self.due_at < (now or timezone.now())


def _photo_path(instance, filename):
    """A random name: the file name of the phone tells nothing (card T30)."""
    return f"reports/{uuid.uuid4().hex}.jpg"


class ReportPhoto(models.Model):
    """A photo, already made smaller and without its metadata (reports/photos.py)."""

    report = models.ForeignKey(
        Report, on_delete=models.CASCADE, related_name="photos", verbose_name="signalement"
    )
    image = models.FileField("photo", upload_to=_photo_path)
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()

    class Meta:
        verbose_name = "photo"
        verbose_name_plural = "photos"
        ordering = ["pk"]

    def __str__(self):
        return f"Photo {self.pk} du signalement n° {self.report_id}"


class ReportEvent(models.Model):
    """One step in the history of a report."""

    class Type(models.TextChoices):
        CREATED = "created", "Signalé"
        ACKNOWLEDGED = "acknowledged", "Pris en charge"
        # Staff only: the resident is not told who handles the report.
        ASSIGNED = "assigned", "Confié"
        SCHEDULED = "scheduled", "Intervention planifiée"
        INTERVENTION = "intervention", "Intervention faite"
        CONFIRMED = "confirmed", "Réglé, confirmé par le résident"
        REOPENED = "reopened", "Pas encore réglé"
        REMINDER = "reminder", "Relance du résident"
        CLOSED = "closed", "Clos"

    report = models.ForeignKey(
        Report, on_delete=models.CASCADE, related_name="events", verbose_name="signalement"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="auteur",
    )
    type = models.CharField("étape", max_length=20, choices=Type.choices)
    note = models.TextField("note", blank=True)
    created_at = models.DateTimeField("date", default=timezone.now)

    class Meta:
        verbose_name = "étape d'un signalement"
        verbose_name_plural = "étapes des signalements"
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"{self.get_type_display()} · signalement n° {self.report_id}"
