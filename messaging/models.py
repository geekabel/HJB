"""Messages from the staff to the residents (cards T20 to T22).

A message template (MessageTemplate) gives the text of a usual message. A
campaign (Campaign) is one message written in the composer: its type, its
text with {fields}, its short SMS version and its recipients. Card T20 keeps
campaigns as drafts; T21 sends them.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .placeholders import check_text


class MessageType(models.TextChoices):
    VISIT = "visit", "Visite de logement"
    MAINTENANCE = "maintenance", "Maintenance"
    ANNOUNCEMENT = "announcement", "Annonce, événement"
    VOTE = "vote", "Vote, avis"
    CUSTOM = "custom", "Message libre"


class ReplyType(models.TextChoices):
    NONE = "none", "Pas de réponse"
    ATTENDANCE = "attendance", "Présent ou absent"


def _check_texts(instance):
    errors = {}
    for field in ("title", "body", "sms_body"):
        problems = check_text(getattr(instance, field))
        if problems:
            errors[field] = problems
    if errors:
        raise ValidationError(errors)


class MessageTemplate(models.Model):
    type = models.CharField("type", max_length=20, choices=MessageType.choices)
    name = models.CharField("nom", max_length=100)
    title = models.CharField(
        "titre",
        max_length=80,
        help_text="Titre de la notification, par exemple « Visite de logement ».",
    )
    body = models.TextField("texte complet", help_text="Affiché dans l'application.")
    sms_body = models.TextField(
        "version SMS",
        blank=True,
        help_text="Courte, pour les résidents sans l'application. Vide : tirée du texte complet.",
    )
    reply_expected = models.BooleanField("demander « Présent » ou « Absent »", default=False)
    updated_at = models.DateTimeField("modifié le", auto_now=True)

    class Meta:
        verbose_name = "modèle de message"
        verbose_name_plural = "modèles de message"
        ordering = ["type", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["type", "name"],
                name="unique_template_name_per_type",
                violation_error_message="Un modèle de ce type porte déjà ce nom.",
            )
        ]

    def __str__(self):
        return f"{self.get_type_display()} · {self.name}"

    def clean(self):
        _check_texts(self)


class Campaign(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Brouillon"
        SCHEDULED = "scheduled", "Programmé"
        SENDING = "sending", "En cours d'envoi"
        SENT = "sent", "Envoyé"
        CANCELLED = "cancelled", "Annulé"

    type = models.CharField(
        "type", max_length=20, choices=MessageType.choices, default=MessageType.ANNOUNCEMENT
    )
    template = models.ForeignKey(
        MessageTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="campaigns",
        verbose_name="modèle",
    )
    title = models.CharField("titre", max_length=80)
    body = models.TextField("texte complet")
    sms_body = models.TextField("version SMS", blank=True)
    reply_type = models.CharField(
        "réponse attendue", max_length=20, choices=ReplyType.choices, default=ReplyType.NONE
    )
    # Values of the {date}, {début} and {fin} fields.
    event_date = models.DateField("date", null=True, blank=True)
    start_time = models.TimeField("début", null=True, blank=True)
    end_time = models.TimeField("fin", null=True, blank=True)

    # Recipients: everyone, or floors, plus rooms and people; minus the removed people.
    everyone = models.BooleanField("tout le monde", default=False)
    floors = models.ManyToManyField(
        "housing.Floor", blank=True, related_name="+", verbose_name="étages"
    )
    rooms = models.ManyToManyField(
        "housing.Room", blank=True, related_name="+", verbose_name="chambres ajoutées"
    )
    people = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="+", verbose_name="personnes ajoutées"
    )
    excluded = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="+", verbose_name="personnes retirées"
    )

    status = models.CharField("état", max_length=20, choices=Status.choices, default=Status.DRAFT)
    send_at = models.DateTimeField("envoi prévu le", null=True, blank=True)
    # Reminder of the people who did not answer (card T21): day of the event at 8:00.
    remind = models.BooleanField("relancer ceux qui n'ont pas répondu", default=False)
    remind_at = models.DateTimeField("relance prévue le", null=True, blank=True)
    reminder_started_at = models.DateTimeField("relance partie le", null=True, blank=True)
    started_at = models.DateTimeField("envoi commencé le", null=True, blank=True)
    sent_at = models.DateTimeField("envoi terminé le", null=True, blank=True)
    reminder_sent_at = models.DateTimeField("relance terminée le", null=True, blank=True)
    # Last task put in the queue (run_due() does not pile them up).
    enqueued_at = models.DateTimeField(null=True, blank=True, editable=False)
    reminder_enqueued_at = models.DateTimeField(null=True, blank=True, editable=False)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="campaigns",
        verbose_name="rédigé par",
    )
    created_at = models.DateTimeField("créé le", auto_now_add=True)
    updated_at = models.DateTimeField("modifié le", auto_now=True)

    class Meta:
        verbose_name = "message"
        verbose_name_plural = "messages"
        ordering = ["-updated_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(start_time__isnull=True)
                | models.Q(end_time__isnull=True)
                | models.Q(end_time__gt=models.F("start_time")),
                name="campaign_end_after_start",
                violation_error_message="L'heure de fin doit venir après l'heure de début.",
            )
        ]

    def __str__(self):
        return self.title

    def clean(self):
        _check_texts(self)


class Delivery(models.Model):
    """One message to one person (card T21): the first sending, or the reminder.

    The unique constraint makes a second sending to the same person impossible,
    even if two workers run the same campaign.
    """

    class Kind(models.TextChoices):
        MESSAGE = "message", "Message"
        REMINDER = "reminder", "Relance"

    class Channel(models.TextChoices):
        PUSH = "push", "Notification"
        SMS = "sms", "SMS"
        NONE = "none", "Aucun moyen de contact"

    class Status(models.TextChoices):
        PENDING = "pending", "En attente"
        SENDING = "sending", "En cours"
        SENT = "sent", "Envoyé"
        FAILED = "failed", "Échec"

    campaign = models.ForeignKey(
        Campaign, on_delete=models.CASCADE, related_name="deliveries", verbose_name="message"
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="deliveries",
        verbose_name="destinataire",
    )
    kind = models.CharField("sorte", max_length=10, choices=Kind.choices, default=Kind.MESSAGE)
    channel = models.CharField("canal", max_length=10, choices=Channel.choices)
    status = models.CharField("état", max_length=10, choices=Status.choices, default=Status.PENDING)
    room_number = models.CharField("chambre", max_length=10, blank=True)
    # The texts as sent, with the fields filled (inbox of card T23).
    title = models.CharField("titre", max_length=80)
    body = models.TextField("texte")
    sms_text = models.TextField("texte du SMS", blank=True)
    segments = models.PositiveSmallIntegerField("SMS facturés", default=0)
    provider_message_id = models.CharField(
        "identifiant chez le fournisseur", max_length=64, blank=True
    )
    error = models.CharField("erreur", max_length=200, blank=True)
    attempts = models.PositiveSmallIntegerField("tentatives", default=0)
    next_attempt_at = models.DateTimeField("prochaine tentative", null=True, blank=True)
    claimed_at = models.DateTimeField("pris en charge le", null=True, blank=True)
    sent_at = models.DateTimeField("envoyé le", null=True, blank=True)
    read_at = models.DateTimeField("lu le", null=True, blank=True)

    class Meta:
        verbose_name = "envoi"
        verbose_name_plural = "envois"
        ordering = ["room_number", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "recipient", "kind"], name="one_delivery_per_person"
            )
        ]
        indexes = [models.Index(fields=["campaign", "status"])]

    def __str__(self):
        return f"{self.campaign} · {self.recipient}"


class AttendanceReply(models.Model):
    """The answer "Présent" or "Absent" of a resident (cards T21 and T22).

    T21 uses it to remind only the people who did not answer; T22 adds the
    buttons to answer.
    """

    class Answer(models.TextChoices):
        PRESENT = "present", "Présent"
        ABSENT = "absent", "Absent"

    campaign = models.ForeignKey(
        Campaign, on_delete=models.CASCADE, related_name="replies", verbose_name="message"
    )
    resident = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="attendance_replies",
        verbose_name="résident",
    )
    answer = models.CharField("réponse", max_length=10, choices=Answer.choices)
    answered_at = models.DateTimeField("répondu le", auto_now=True)

    class Meta:
        verbose_name = "réponse présent ou absent"
        verbose_name_plural = "réponses présent ou absent"
        constraints = [
            models.UniqueConstraint(fields=["campaign", "resident"], name="one_reply_per_resident")
        ]

    def __str__(self):
        return f"{self.resident} · {self.get_answer_display()}"
