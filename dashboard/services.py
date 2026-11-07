"""What the staff dashboard shows (card T35, mockup P1).

Each part depends on what the person may do: reports for those who handle
them, messages and the visit rotation for those who send messages, wifi for
those who see residents. The meetings of the day are only counted: their
reason stays between the resident and the educator.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from django.db.models import Count, Exists, Max, OuterRef, Q
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

LATE_SHOWN = 5
VISITS_SHOWN = 5
SCHEDULED_SHOWN = 5
# run_scheduled starts a programmed message within the minute; past this
# delay, the message is stuck (worker stopped) and the dashboard says so.
STUCK_AFTER = timedelta(minutes=5)


@dataclass(frozen=True)
class Figure:
    label: str
    value: int
    detail: str = ""
    url: str = ""
    warn: bool = False


def _today_bounds(now):
    day = timezone.localtime(now).date()
    start = timezone.make_aware(datetime.combine(day, time.min))
    return start, timezone.make_aware(datetime.combine(day, time.max))


def figures(user, now):
    from django.urls import reverse

    from appointments.models import Appointment
    from housing.models import WifiAccess
    from messaging.models import Campaign
    from reports.models import Report

    found = []
    if user.has_perm("accounts.manage_reports"):
        open_reports = Report.objects.exclude(status=Report.Status.CLOSED)
        late = open_reports.filter(status__in=Report.WAITING, due_at__lte=now).count()
        found.append(
            Figure(
                "Signalements ouverts",
                open_reports.count(),
                f"dont {late} en retard" if late else "aucun en retard",
                reverse("reports_staff:board"),
                warn=bool(late),
            )
        )
    if user.has_perm("accounts.send_messages"):
        scheduled = Campaign.objects.filter(status=Campaign.Status.SCHEDULED)
        stuck = scheduled.filter(send_at__lt=now - STUCK_AFTER).count()
        first = (
            scheduled.filter(send_at__gte=now - STUCK_AFTER)
            .order_by("send_at")
            .values_list("send_at", flat=True)
            .first()
        )
        if stuck:
            detail = f"dont {stuck} en attente, pas parti{'s' if stuck > 1 else ''}"
        elif first:
            detail = f"prochain : {_short_moment(first, now)}"
        else:
            detail = ""
        found.append(
            Figure(
                "Messages programmés",
                scheduled.count(),
                detail,
                reverse("messaging:list"),
                warn=bool(stuck),
            )
        )
    start, end = _today_bounds(now)
    meetings = Appointment.objects.filter(
        status=Appointment.Status.CONFIRMED, start__range=(start, end)
    ).select_related("educator")
    per_educator = Counter(m.educator.first_name or m.educator.get_username() for m in meetings)
    found.append(
        Figure(
            "Rendez-vous aujourd'hui",
            sum(per_educator.values()),
            " · ".join(f"{name} {count}" for name, count in sorted(per_educator.items())),
        )
    )
    if user.has_perm("accounts.view_residents"):
        renew = WifiAccess.objects.to_renew().count()
        found.append(
            Figure(
                "Wifi à renouveler",
                renew,
                "sous 30 jours ou fini",
                reverse("residents:wifi_renewals"),
                warn=bool(renew),
            )
        )
    return found


def _short_moment(moment, now):
    from django.utils.formats import date_format

    local = timezone.localtime(moment)
    today = timezone.localtime(now).date()
    if local.date() == today:
        day = "aujourd'hui"
    elif (local.date() - today).days == 1:
        day = "demain"
    else:
        day = date_format(local, "D j N")
    return f"{day} {local:%H:%M}"


def late_reports(now):
    from reports.models import Report

    reports = list(
        Report.objects.filter(status__in=Report.WAITING, due_at__lte=now)
        .select_related("room", "assigned_to")
        .order_by("due_at")[:LATE_SHOWN]
    )
    for report in reports:
        report.delay = report.delay_text(now)
    return reports


@dataclass(frozen=True)
class VisitReplies:
    campaign: object
    title: str
    asked: int
    present: int
    absent: int

    @property
    def answered(self):
        return self.present + self.absent


def visit_replies(now):
    """The visits to come that ask "Présent ou Absent", with their answers."""
    from messaging.models import AttendanceReply, Campaign, Delivery, ReplyType
    from messaging.placeholders import fill, values_for

    day = timezone.localtime(now).date()
    campaigns = (
        Campaign.objects.filter(
            reply_type=ReplyType.ATTENDANCE,
            status__in=(Campaign.Status.SENDING, Campaign.Status.SENT),
            event_date__gte=day,
        )
        .annotate(
            asked=Count(
                "deliveries",
                filter=Q(deliveries__kind=Delivery.Kind.MESSAGE),
                distinct=True,
            ),
            present=Count(
                "replies",
                filter=Q(replies__answer=AttendanceReply.Answer.PRESENT),
                distinct=True,
            ),
            absent=Count(
                "replies",
                filter=Q(replies__answer=AttendanceReply.Answer.ABSENT),
                distinct=True,
            ),
        )
        .prefetch_related("floors")
        .order_by("event_date", "pk")[:VISITS_SHOWN]
    )
    return [
        VisitReplies(c, fill(c.title, values_for(c)), c.asked, c.present, c.absent)
        for c in campaigns
    ]


def scheduled_messages(now):
    """The programmed messages, the stuck ones first (their time is past)."""
    from messaging.models import Campaign
    from messaging.placeholders import fill, values_for

    campaigns = list(
        Campaign.objects.filter(status=Campaign.Status.SCHEDULED)
        .prefetch_related("floors")
        .annotate(
            room_count=Count("rooms", distinct=True), people_count=Count("people", distinct=True)
        )
        .order_by("send_at")[:SCHEDULED_SHOWN]
    )
    for campaign in campaigns:
        campaign.when = _short_moment(campaign.send_at, now)
        campaign.audience = _audience(campaign)
        campaign.display_title = fill(campaign.title, values_for(campaign))
        campaign.stuck = campaign.send_at < now - STUCK_AFTER
    return campaigns


def _audience(campaign):
    if campaign.everyone:
        return "Tous les résidents"
    parts = [str(floor) for floor in campaign.floors.all()]
    if campaign.room_count:
        parts.append(f"{campaign.room_count} chambre{'s' if campaign.room_count > 1 else ''}")
    if campaign.people_count:
        parts.append(f"{campaign.people_count} personne{'s' if campaign.people_count > 1 else ''}")
    return ", ".join(parts)


@dataclass(frozen=True)
class RotationStep:
    floor: object
    last_visit: object  # a date, or None
    is_last: bool
    is_next: bool


def rotation():
    """The floors where someone lives, in their visit order
    (Floor.visit_order), the last one visited and the next one.

    A visit is a message of type "Visite" that asks "Présent ou Absent"
    (a cancel notice does not count), sent to a floor: programmed, being
    sent or sent. Its day is the event date, or else the sending day. When
    one visit covers several floors, the last of them in the order is the
    last visited: the rotation goes on after it.
    """
    from housing.models import Floor, Stay
    from messaging.models import Campaign, MessageType, ReplyType

    lived_in = Stay.objects.filter(room__floor=OuterRef("pk"), departure__isnull=True)
    floors = list(Floor.objects.filter(Exists(lived_in)).order_by("visit_order", "number"))
    if not floors:
        return []
    zone = timezone.get_current_timezone()
    visits = (
        Campaign.objects.filter(
            type=MessageType.VISIT,
            reply_type=ReplyType.ATTENDANCE,
            status__in=(Campaign.Status.SCHEDULED, Campaign.Status.SENDING, Campaign.Status.SENT),
            floors__isnull=False,
        )
        .annotate(
            day=Coalesce(
                "event_date",
                TruncDate(Coalesce("send_at", "started_at", "created_at"), tzinfo=zone),
            )
        )
        .values("floors")
        .annotate(last=Max("day"))
    )
    last_of = {row["floors"]: row["last"] for row in visits}
    visited = [f for f in floors if last_of.get(f.pk)]
    if visited:
        last = max(visited, key=lambda f: (last_of[f.pk], floors.index(f)))
        following = floors[(floors.index(last) + 1) % len(floors)]
    else:
        last, following = None, floors[0]
    return [RotationStep(f, last_of.get(f.pk), f is last, f is following) for f in floors]
