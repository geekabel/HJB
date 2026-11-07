"""What waits for a resident, for the home page (design card D2, card T34).

The home page answers "what do I have to do?": a message that asks
"Présent ou Absent", an open vote, a repair to confirm, a new message from
an educator, a meeting in the next 48 hours, a wifi access about to end.

The first one leads the page in a card with its own button. What is due
today comes first (a meeting today, a wifi access ending today or over),
then the answers asked, the repairs to confirm, the new messages, the other
meetings and the wifi soon over. Only the answers are cut after a few: the
"Voir tout" link opens them in the inbox; the other kinds are always shown.
"""

from dataclasses import dataclass
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

# Order of the kinds on the page (lower first)
NOW, ANSWER, REPAIR, UNREAD, MEETING, WIFI = range(6)


@dataclass(frozen=True)
class Todo:
    title: str
    detail: str
    url: str
    icon: str
    lead: str = ""  # shown above the title when it leads the home page
    action: str = "Voir"  # the button of the leading card
    rank: int = ANSWER
    is_answer: bool = False  # a message that asks an answer (cut after SHOWN)


SHOWN = 5  # answers shown on the home page; more: a link to the inbox


def todos(user, unread_direct=None, stay=None):
    """Everything that waits, in page order. ``stay``: the current stay, when
    already known (one query less)."""
    from appointments import booking, direct
    from housing import wifi
    from housing.models import WIFI_REMINDER_DAYS
    from housing.services import current_stay
    from messaging import inbox
    from reports.models import Report

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
                is_answer=True,
            )
        )
    for report in Report.objects.filter(resident=user, status=Report.Status.DONE):
        found.append(
            Todo(
                title=f"{report.get_category_display()} : c'est réglé ?",
                detail="L'intervention est faite",
                url=reverse("reports:detail", args=[report.pk]),
                icon="tool",
                lead="Signalement · réponse attendue",
                action="Répondre",
                rank=REPAIR,
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
                lead="Message d'un éducateur",
                action="Lire",
                rank=UNREAD,
            )
        )
    soon = timezone.now() + timedelta(hours=48)
    today = timezone.localdate()
    for meeting in booking.upcoming(user).filter(start__lte=soon).order_by("start"):
        start = timezone.localtime(meeting.start)
        who = meeting.educator.first_name or meeting.educator.get_username()
        found.append(
            Todo(
                title=f"Rendez-vous avec {who}",
                detail=f"{_day(start)} à {start:%H:%M}",
                url=reverse("rdv:detail", args=[meeting.pk]),
                icon="calendar",
                lead="Rendez-vous",
                action="Voir le rendez-vous",
                rank=NOW if start.date() == today else MEETING,
            )
        )
    stay = stay if stay is not None else current_stay(user)
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
                lead="Wifi",
                action="Voir mon wifi",
                rank=NOW if days <= 0 else WIFI,
            )
        )
    return sorted(found, key=lambda todo: todo.rank)  # stable: same kind keeps its order


def page(found):
    """What the home page shows: (lead, others, answers not shown)."""
    answers = [todo for todo in found if todo.is_answer]
    hidden = set(map(id, answers[SHOWN:]))
    shown = [todo for todo in found if id(todo) not in hidden]
    return (shown[0] if shown else None), shown[1:], len(hidden)


def _day(start):
    from django.utils.formats import date_format

    today = timezone.localdate()
    if start.date() == today:
        return "Aujourd'hui"
    if start.date() == today + timedelta(days=1):
        return "Demain"
    return date_format(start, "l j F").capitalize()


MY_REPORTS = 2  # on the home page; the Signaler tab has them all
NEWS_DAYS = 30  # an older announcement is not "news" any more


def open_reports(user):
    """My reports not closed yet, the last moved first (card T34)."""
    from reports.models import Report

    return list(
        Report.objects.filter(resident=user)
        .exclude(status=Report.Status.CLOSED)
        .order_by("-updated_at")[:MY_REPORTS]
    )


def latest_announcement(user, now=None):
    """The last announcement this person received in the last 30 days (card T34)."""
    from messaging.inbox import received
    from messaging.models import MessageType

    since = (now or timezone.now()) - timedelta(days=NEWS_DAYS)
    return (
        received(user)
        .filter(campaign__type=MessageType.ANNOUNCEMENT, received_at__gte=since)
        .first()
    )
