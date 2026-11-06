"""What waits for a resident, for the home page (design card D2).

The home page answers "what do I have to do?": a message that asks
"Présent ou Absent", an open vote, a new message from an educator, a meeting
in the next 48 hours, a wifi access about to end. The full home page with
the repair reports comes with card T34.
"""

from dataclasses import dataclass
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone


@dataclass(frozen=True)
class Todo:
    title: str
    detail: str
    url: str
    icon: str


SHOWN = 5  # more than that: a link to the full list


def todos(user, unread_direct=None):
    from appointments import booking, direct
    from housing import wifi
    from housing.models import WIFI_REMINDER_DAYS
    from housing.services import current_stay
    from messaging import inbox

    found = []
    for item in inbox.to_answer(user):
        found.append(
            Todo(
                title=item.delivery.title,
                detail="Votez" if item.vote_waiting else "Dites si vous serez là",
                url=reverse("inbox:message", args=[item.campaign.pk]),
                icon="vote" if item.vote_waiting else "door",
            )
        )
    unread = direct.unread_count(user) if unread_direct is None else unread_direct
    if unread:
        plural = unread > 1
        found.append(
            Todo(
                title=f"{unread} nouveau{'x' if plural else ''} message{'s' if plural else ''}",
                detail="D'un éducateur",
                url=reverse("inbox:list"),
                icon="message",
            )
        )
    soon = timezone.now() + timedelta(hours=48)
    for meeting in booking.upcoming(user).filter(start__lte=soon).order_by("start"):
        start = timezone.localtime(meeting.start)
        who = meeting.educator.first_name or meeting.educator.get_username()
        found.append(
            Todo(
                title=f"Rendez-vous avec {who}",
                detail=f"{_day(start)} à {start:%H:%M}",
                url=reverse("rdv:detail", args=[meeting.pk]),
                icon="calendar",
            )
        )
    stay = current_stay(user)
    access = wifi.current_access(stay.room) if stay else None
    if access is not None and access.days_left <= WIFI_REMINDER_DAYS:
        days = access.days_left
        if days < 0:
            title = "Wifi expiré"
        elif days == 0:
            title = "Wifi : dernier jour"
        else:
            title = f"Wifi : encore {days} jour{'s' if days > 1 else ''}"
        found.append(
            Todo(
                title=title,
                detail="Passez à l'accueil pour le renouveler.",
                url=reverse("housing:my_wifi"),
                icon="wifi",
            )
        )
    return found


def _day(start):
    from django.utils.formats import date_format

    today = timezone.localdate()
    if start.date() == today:
        return "Aujourd'hui"
    if start.date() == today + timedelta(days=1):
        return "Demain"
    return date_format(start, "l j F").capitalize()
