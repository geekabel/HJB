"""Appointments with an educator (cards T26 to T29).

T26: each educator opens times in a weekly grid (Availability, repeated every
week) and sets the length of a meeting and how late a resident can book
(EducatorSettings).
T27: a resident books a meeting (Appointment); an educator closes days
(Absence); French public holidays are closed too (holidays.py).
T28: a resident and an educator write to each other (Conversation,
DirectMessage); the educator shows when they usually answer (reply_hours).
T29: reminders the day before and one hour before, and cancellation by the
resident or the educator, with a notice to the other person.
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
    remind_residents = models.BooleanField(
        "rappel au résident la veille et 1 h avant", default=True
    )
    reply_hours = models.CharField(
        "heures de réponse aux messages",
        max_length=100,
        default="du lundi au vendredi, de 9 h à 17 h",
        help_text="Montré aux résidents avant qu'ils vous écrivent.",
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


class Appointment(models.Model):
    """A meeting booked by a resident with an educator (card T27).

    The reason is short and optional; only the educator of the meeting reads
    it (not the other staff members, not the admin site).
    """

    class Status(models.TextChoices):
        CONFIRMED = "confirmed", "Confirmé"
        CANCELLED = "cancelled", "Annulé"

    class Reason(models.TextChoices):
        NONE = "", "Je préfère en parler sur place"
        PAPERS = "papers", "Démarches administratives"
        WORK = "work", "Emploi, formation"
        BUDGET = "budget", "Budget"
        HOUSING = "housing", "Logement"
        OTHER = "other", "Autre"

    educator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="appointments_given",
        verbose_name="éducateur",
    )
    resident = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="appointments",
        verbose_name="résident",
    )
    start = models.DateTimeField("début")
    end = models.DateTimeField("fin")
    reason = models.CharField("motif", max_length=20, choices=Reason.choices, blank=True)
    status = models.CharField(
        "état", max_length=12, choices=Status.choices, default=Status.CONFIRMED
    )
    created_at = models.DateTimeField("pris le", auto_now_add=True)
    # Reminders (card T29): claimed before they leave, never sent twice.
    day_before_sent_at = models.DateTimeField(null=True, blank=True, editable=False)
    hour_before_sent_at = models.DateTimeField(null=True, blank=True, editable=False)
    cancelled_at = models.DateTimeField("annulé le", null=True, blank=True)
    # Empty for a cancellation by the system (a departure).
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="annulé par",
    )

    class Meta:
        verbose_name = "rendez-vous"
        verbose_name_plural = "rendez-vous"
        ordering = ["start"]
        constraints = [
            # No double booking, whatever happens in the code.
            models.UniqueConstraint(
                fields=["educator", "start"],
                condition=models.Q(status="confirmed"),
                name="one_meeting_per_educator_start",
                violation_error_message="Ce créneau est déjà pris.",
            ),
            models.CheckConstraint(
                condition=models.Q(end__gt=models.F("start")),
                name="appointment_end_after_start",
                violation_error_message="La fin doit venir après le début.",
            ),
        ]
        indexes = [models.Index(fields=["educator", "status", "start"])]

    def __str__(self):
        # Neutral: the admin lists cascaded objects with it (who met whom).
        return f"Rendez-vous n°{self.pk}"

    @property
    def minutes(self):
        return int((self.end - self.start).total_seconds() // 60)


class Absence(models.Model):
    """Days an educator is away (holidays, training): no booking (card T27)."""

    educator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="absences",
        verbose_name="éducateur",
    )
    first_day = models.DateField("du")
    last_day = models.DateField("au")

    class Meta:
        verbose_name = "absence"
        verbose_name_plural = "absences"
        ordering = ["first_day"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(last_day__gte=models.F("first_day")),
                name="absence_last_after_first",
                violation_error_message="Le dernier jour ne peut pas précéder le premier.",
            )
        ]

    def __str__(self):
        return f"{self.educator} · {self.first_day} → {self.last_day}"


class Conversation(models.Model):
    """Direct messages between one resident and one educator (card T28).

    Only these two people read it: not the rest of the staff, not the admin.
    """

    resident = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="conversations",
        verbose_name="résident",
    )
    educator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="conversations_as_educator",
        verbose_name="éducateur",
    )
    updated_at = models.DateTimeField("dernier message le", auto_now_add=True)

    class Meta:
        verbose_name = "conversation"
        verbose_name_plural = "conversations"
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["resident", "educator"], name="one_conversation_per_pair"
            )
        ]

    def __str__(self):
        # Neutral: the admin lists cascaded objects with it.
        return f"Conversation n°{self.pk}"


class DirectMessage(models.Model):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+", verbose_name="auteur"
    )
    text = models.TextField("message", max_length=2000)
    sent_at = models.DateTimeField("envoyé le", auto_now_add=True)
    read_at = models.DateTimeField("lu le", null=True, blank=True)

    class Meta:
        verbose_name = "message direct"
        verbose_name_plural = "messages directs"
        ordering = ["sent_at", "pk"]
        indexes = [models.Index(fields=["conversation", "read_at"])]

    def __str__(self):
        return f"Message n°{self.pk}"
