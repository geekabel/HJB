"""Who receives a campaign, and by which channel (card T20).

Recipients are current residents (active account, current stay), plus the
people added one by one (even without a room), minus the people removed.
Channel: a notification if the person has at least one device (card T19),
otherwise an SMS if they have a phone number, otherwise nothing.
"""

from dataclasses import dataclass, field

from django.db.models import Exists, OuterRef

from accounts.models import User
from housing.models import Stay
from push.models import PushSubscription

from .placeholders import fill, values_for
from .sms_text import sms_text


@dataclass
class Recipient:
    user: object
    room: object  # None for a person added without a room
    channel: str  # "push", "sms" or "none"


@dataclass
class Audience:
    recipients: list = field(default_factory=list)

    def _count(self, channel):
        return sum(1 for r in self.recipients if r.channel == channel)

    @property
    def total(self):
        return len(self.recipients)

    @property
    def push(self):
        return self._count("push")

    @property
    def sms(self):
        return self._count("sms")

    @property
    def unreachable(self):
        return self._count("none")


def audience(campaign, *, floors=None, rooms=None, people=None, excluded=None, everyone=None):
    """The recipients of ``campaign``. Keyword arguments override its saved targets
    (used by the composer before the draft is saved)."""
    everyone = campaign.everyone if everyone is None else everyone
    if campaign.pk:
        floors = list(campaign.floors.all()) if floors is None else floors
        rooms = list(campaign.rooms.all()) if rooms is None else rooms
        people = list(campaign.people.all()) if people is None else people
        excluded = list(campaign.excluded.all()) if excluded is None else excluded
    floors, rooms, people, excluded = floors or [], rooms or [], people or [], excluded or []

    stays = Stay.objects.current().filter(resident__is_active=True)
    stays = stays.filter(resident__in=User.objects.residents())
    if not everyone:
        stays = stays.filter(room__floor__in=floors) | stays.filter(room__in=rooms)
    stays = stays.select_related("resident", "room").order_by("room__number")
    room_of = {stay.resident_id: stay.room for stay in stays}
    users = {stay.resident_id: stay.resident for stay in stays}
    # People added one by one: still residents (no staff role since), still active.
    added = User.objects.residents().filter(pk__in=[p.pk for p in people], is_active=True)
    added_rooms = {
        stay.resident_id: stay.room
        for stay in Stay.objects.current().filter(resident__in=added).select_related("room")
    }
    for person in added:
        users.setdefault(person.pk, person)
        room_of.setdefault(person.pk, added_rooms.get(person.pk))
    for person in excluded:
        users.pop(person.pk, None)

    with_device = set(
        User.objects.filter(pk__in=users)
        .filter(Exists(PushSubscription.objects.filter(user=OuterRef("pk"))))
        .values_list("pk", flat=True)
    )
    recipients = []
    for pk, user in users.items():
        if pk in with_device:
            channel = "push"
        elif user.phone:
            channel = "sms"
        else:
            channel = "none"
        recipients.append(Recipient(user, room_of.get(pk), channel))
    recipients.sort(key=lambda r: ((r.room.number if r.room else "~"), r.user.last_name))
    return Audience(recipients)


def rendered(campaign, recipient):
    """(full text, SMS text) for one recipient.

    A message that asks for an answer ends its SMS with the personal reply link
    (card T22): it counts in the length, so it is in the previews and costs too.
    """
    from .models import ReplyType
    from .replies import sms_suffix

    values = values_for(campaign, recipient.user, recipient.room)
    sms = sms_text(fill(campaign.sms_body or campaign.body, values))
    if campaign.reply_type == ReplyType.ATTENDANCE:
        user_id = recipient.user.pk if recipient.user else 0
        sms += sms_suffix(campaign.pk or 0, user_id or 0)
    return fill(campaign.body, values), sms
