"""Appointments with an educator (cards T26 to T29).

T26: each educator opens times in a weekly grid (Availability, repeated every
week) and sets the length of a meeting and how late a resident can book
(EducatorSettings).
"""

from django.conf import settings
from django.db import models


class EducatorSettings(models.Model):
    class Notice(models.TextChoices):
        TWO_HOURS = "2h", "2 heures avant"
        DAY_BEFORE = "day_before", "La veille"

    educator = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="educator_settings",
        verbose_name="éducateur",
    )
    slot_minutes = models.PositiveSmallIntegerField(
        "durée d'un rendez-vous",
        choices=[(30, "30 minutes"), (45, "45 minutes"), (60, "1 heure")],
        default=30,
    )
    notice = models.CharField(
        "réserver au plus tard", max_length=12, choices=Notice.choices, default=Notice.TWO_HOURS
    )

    class Meta:
        verbose_name = "réglages d'un éducateur"
        verbose_name_plural = "réglages des éducateurs"

    def __str__(self):
        return str(self.educator)


class Availability(models.Model):
    """Open to booking, every week, on this day between these hours."""

    class Weekday(models.IntegerChoices):
        MONDAY = 0, "lundi"
        TUESDAY = 1, "mardi"
        WEDNESDAY = 2, "mercredi"
        THURSDAY = 3, "jeudi"
        FRIDAY = 4, "vendredi"
        SATURDAY = 5, "samedi"
        SUNDAY = 6, "dimanche"

    educator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="availabilities",
        verbose_name="éducateur",
    )
    weekday = models.PositiveSmallIntegerField("jour", choices=Weekday.choices)
    start = models.TimeField("début")
    end = models.TimeField("fin")

    class Meta:
        verbose_name = "disponibilité"
        verbose_name_plural = "disponibilités"
        ordering = ["educator", "weekday", "start"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end__gt=models.F("start")),
                name="availability_end_after_start",
                violation_error_message="La fin doit venir après le début.",
            ),
            models.UniqueConstraint(
                fields=["educator", "weekday", "start"], name="one_availability_per_start"
            ),
        ]

    def __str__(self):
        return f"{self.get_weekday_display()} {self.start:%H:%M}-{self.end:%H:%M}"
