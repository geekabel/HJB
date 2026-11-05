"""Inbox of a resident (card T23): the messages received, by kind, read or not.

A message is unread until the person opens it in the application or answers
with a button (link of the SMS, notification). Opening the SMS link alone does
not count: SMS apps open links by themselves to make a preview.
"""

from dataclasses import dataclass

from django.db.models import F
from django.db.models.functions import Coalesce
from django.utils import timezone

from polls.models import Participation, Poll
from polls.services import is_open as polls_open

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

    Sorted by the time the person got it (a retry can come later than the
    start of the sending). Failed deliveries stay: the SMS did not leave, but
    the application shows the message anyway.
    """
    return (
        Delivery.objects.filter(
            recipient=user,
            kind=Delivery.Kind.MESSAGE,
            campaign__status__in=(Campaign.Status.SENDING, Campaign.Status.SENT),
        )
        .select_related("campaign")
        .annotate(received_at=Coalesce("sent_at", "campaign__started_at"))
        .order_by(F("received_at").desc(nulls_last=True), "-pk")
    )


def inbox(user, key="all"):
    deliveries = received(user)
    if key == "mine":
        return deliveries.filter(personal=True)
    if key in FILTER_KEYS - {"all"}:
        return deliveries.filter(campaign__type=key)
    return deliveries


def unread_count(user, key="all"):
    if not user.is_authenticated:
        return 0
    return inbox(user, key).filter(read_at__isnull=True).count()


def mark_all_read(user, key="all"):
    """Only the messages of the list shown: the others were not seen."""
    return inbox(user, key).filter(read_at__isnull=True).update(read_at=timezone.now())


@dataclass
class Item:
    delivery: Delivery
    short_type: str
    answer: str  # "present", "absent" or ""
    waiting: bool  # a "Présent" or "Absent" answer is expected
    poll: object = None  # a vote (card T25)
    poll_open: bool = False
    voted: bool = False
    vote_waiting: bool = False

    @property
    def campaign(self):
        return self.delivery.campaign

    @property
    def unread(self):
        return self.delivery.read_at is None

    @property
    def when(self):
        return self.delivery.received_at

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
    ids = [d.campaign_id for d in deliveries]
    poll_of = {poll.campaign_id: poll for poll in Poll.objects.filter(campaign_id__in=ids)}
    voted = set(
        Participation.objects.filter(resident=user, poll__campaign_id__in=ids).values_list(
            "poll__campaign_id", flat=True
        )
    )
    now = timezone.now()
    rows = []
    for delivery in deliveries:
        campaign = delivery.campaign
        answer = answers.get(campaign.pk, "")
        asks = campaign.reply_type == ReplyType.ATTENDANCE
        poll = poll_of.get(campaign.pk)
        if poll is not None:
            poll.campaign = campaign  # already loaded: no query in is_open()
        rows.append(
            Item(
                delivery=delivery,
                short_type=SHORT_TYPES.get(campaign.type, "Message"),
                answer=answer if asks else "",
                waiting=asks and not answer and replies.is_open(campaign, now),
                poll=poll,
                poll_open=poll is not None and polls_open(poll, now),
                voted=campaign.pk in voted,
                vote_waiting=poll is not None
                and campaign.pk not in voted
                and polls_open(poll, now),
            )
        )
    return rows
