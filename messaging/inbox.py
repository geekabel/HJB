"""Inbox of a resident (card T23): the messages received, by kind, read or not.

A message is unread until the person opens it in the application or answers
with a button (link of the SMS, notification). Opening the SMS link alone does
not count: SMS apps open links by themselves to make a preview.
"""

from dataclasses import dataclass

from django.db.models import BooleanField, Exists, ExpressionWrapper, OuterRef, Q
from django.utils import timezone

from . import replies
from .models import AttendanceReply, Campaign, Delivery, MessageType, ReplyType


@dataclass(frozen=True)
class Filter:
    key: str
    label: str
    empty: str


FILTERS = (
    Filter("all", "Tous", "Aucun message pour le moment."),
    Filter("visit", "Visites", "Aucune visite annoncée."),
    Filter("announcement", "Annonces", "Aucune annonce."),
    Filter("vote", "Votes", "Aucun vote ni demande d'avis."),
    Filter("mine", "Pour moi", "Aucun message qui vous est adressé personnellement."),
)
FILTER_KEYS = {item.key for item in FILTERS}

# Short names of the types, before the title in the list.
SHORT_TYPES = {
    MessageType.VISIT: "Visite",
    MessageType.MAINTENANCE: "Maintenance",
    MessageType.ANNOUNCEMENT: "Annonce",
    MessageType.VOTE: "Vote",
    MessageType.CUSTOM: "Message",
}


def received(user):
    """Messages that reached this person (or were meant to), newest first.

    Failed deliveries stay: the SMS did not leave, but the application shows
    the message anyway.
    """
    return (
        Delivery.objects.filter(
            recipient=user,
            kind=Delivery.Kind.MESSAGE,
            campaign__status__in=(Campaign.Status.SENDING, Campaign.Status.SENT),
        )
        .select_related("campaign")
        .order_by("-campaign__started_at", "-pk")
    )


def _personal():
    """Sent to this person by name or to the room, not to everyone or a whole floor."""
    by_name = Exists(
        Campaign.people.through.objects.filter(
            campaign_id=OuterRef("campaign_id"), user_id=OuterRef("recipient_id")
        )
    )
    by_room = Exists(
        Campaign.rooms.through.objects.filter(
            campaign_id=OuterRef("campaign_id"), room__number=OuterRef("room_number")
        )
    )
    return Q(campaign__everyone=False) & (Q(by_name) | Q(by_room))


def inbox(user, key="all"):
    deliveries = received(user).annotate(
        personal=ExpressionWrapper(_personal(), output_field=BooleanField())
    )
    if key == "mine":
        return deliveries.filter(personal=True)
    if key in FILTER_KEYS - {"all"}:
        return deliveries.filter(campaign__type=key)
    return deliveries


def unread_count(user):
    if not user.is_authenticated:
        return 0
    return received(user).filter(read_at__isnull=True).count()


def mark_all_read(user):
    return received(user).filter(read_at__isnull=True).update(read_at=timezone.now())


@dataclass
class Item:
    delivery: Delivery
    short_type: str
    answer: str  # "present", "absent" or ""
    waiting: bool  # a "Présent" or "Absent" answer is expected

    @property
    def campaign(self):
        return self.delivery.campaign

    @property
    def unread(self):
        return self.delivery.read_at is None

    @property
    def when(self):
        return self.delivery.sent_at or self.campaign.started_at

    @property
    def answer_label(self):
        return AttendanceReply.Answer(self.answer).label if self.answer else ""


def items(user, deliveries):
    """The rows of one page, with the answer of the person when one is asked."""
    deliveries = list(deliveries)
    answers = dict(
        AttendanceReply.objects.filter(
            resident=user, campaign_id__in=[d.campaign_id for d in deliveries]
        ).values_list("campaign_id", "answer")
    )
    now = timezone.now()
    rows = []
    for delivery in deliveries:
        campaign = delivery.campaign
        answer = answers.get(campaign.pk, "")
        asks = campaign.reply_type == ReplyType.ATTENDANCE
        rows.append(
            Item(
                delivery=delivery,
                short_type=SHORT_TYPES.get(campaign.type, "Message"),
                answer=answer if asks else "",
                waiting=asks and not answer and replies.is_open(campaign, now),
            )
        )
    return rows
