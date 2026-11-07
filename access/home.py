"""What waits for a resident, for the home page (design card D2).

The home page answers "what do I have to do?": a message that asks
"Présent ou Absent", an open vote, a repair to confirm, a new message from
an educator, a meeting in the next 48 hours, a wifi access about to end.
The first one leads the page (card T34): ``lead`` says what kind it is.
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
    lead: str = ""  # shown above the title when it leads the home page
    action: str = "Voir"  # the button of the leading card


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
                lead="Vote ouvert"
                if item.vote_waiting
                else f"{item.short_type} · réponse attendue",
                action="Voter" if item.vote_waiting else "Répondre",
            )
        )
    from reports.models import Report

    for report in Report.objects.filter(resident=user, status=Report.Status.DONE):
        found.append(
            Todo(
                title=f"{report.get_category_display()} : c'est réglé ?",
                detail="L'intervention est faite",
                url=reverse("reports:detail", args=[report.pk]),
                icon="tool",
                lead="Signalement · réponse attendue",
                action="Répondre",
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


MY_REPORTS = 2  # on the home page; the Signaler tab has them all


def open_reports(user):
    """My reports not closed yet, the last moved first (card T34)."""
    from reports.models import Report

    return list(
        Report.objects.filter(resident=user)
        .exclude(status=Report.Status.CLOSED)
        .order_by("-updated_at")[:MY_REPORTS]
    )


def latest_announcement(user):
    """The last announcement this person received, or None (card T34)."""
    from messaging.inbox import received
    from messaging.models import MessageType

    return received(user).filter(campaign__type=MessageType.ANNOUNCEMENT).first()
