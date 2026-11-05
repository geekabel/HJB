"""Booking of a meeting by a resident (card T27).

A resident chooses an educator, or "le premier libre", then a day and a time
among the bookable times (availability.bookable) that nobody booked yet.

No double booking: the booking runs in a transaction that locks the educator
row, checks again that the time is still free (no overlap, even after a change
of length), and the database refuses two confirmed meetings with the same
educator at the same start (unique constraint).
"""

from collections import Counter
from datetime import datetime, time, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import User
from accounts.roles import GROUP_BY_ROLE, Role

from . import availability
from .models import Absence, Appointment, Availability, EducatorSettings

DAYS_AHEAD = 14  # how far ahead a resident can book: today and the 13 next days
MAX_UPCOMING = 2  # meetings a resident can hold at once


TAKEN = "Ce créneau n'est plus libre. Choisissez-en un autre."


class BookingRefused(Exception):
    """French message for the resident."""


def educators():
    """Educators a resident can book with: active, with at least one open time."""
    return (
        User.objects.filter(
            is_active=True,
            groups__name=GROUP_BY_ROLE[Role.EDUCATOR],
            availabilities__isnull=False,
        )
        .distinct()
        .order_by("first_name", "last_name")
    )


def _busy(educator_ids, first, last):
    """Confirmed meetings in [first, last), by educator id."""
    found = {}
    for meeting in Appointment.objects.filter(
        educator_id__in=educator_ids,
        status=Appointment.Status.CONFIRMED,
        start__lt=last,
        end__gt=first,
    ):
        found.setdefault(meeting.educator_id, []).append((meeting.start, meeting.end))
    return found


def _free(slot, busy):
    return all(slot.end <= start or slot.start >= end for start, end in busy)


class Planner:
    """The free slots of some educators over some days, with few queries."""

    def __init__(self, people, first_day, last_day):
        self.people = list(people)
        ids = [person.pk for person in self.people]
        self.settings = {
            row.educator_id: row for row in EducatorSettings.objects.filter(educator_id__in=ids)
        }
        self.ranges = {}
        for row in Availability.objects.filter(educator_id__in=ids):
            self.ranges.setdefault(row.educator_id, []).append(row)
        self.absences = {}
        for row in Absence.objects.filter(
            educator_id__in=ids, last_day__gte=first_day, first_day__lte=last_day
        ):
            self.absences.setdefault(row.educator_id, []).append(row)
        start = timezone.make_aware(datetime.combine(first_day, time(0, 0)))
        end = timezone.make_aware(datetime.combine(last_day + timedelta(days=1), time(0, 0)))
        self.busy = _busy(ids, start, end)

    def free(self, day, now=None):
        """Free slots on ``day``, sorted by time."""
        slots = []
        for person in self.people:
            if person.pk not in self.ranges:
                continue
            for slot in availability.bookable(
                person,
                day,
                now,
                settings=self.settings.get(person.pk) or EducatorSettings(educator=person),
                availabilities=self.ranges[person.pk],
                absences=self.absences.get(person.pk, []),
            ):
                if _free(slot, self.busy.get(person.pk, [])):
                    slots.append(slot)
        slots.sort(key=lambda slot: (slot.start, slot.educator.first_name))
        return slots


def free_slots(people, day, now=None):
    """Free slots of ``people`` (educators) on ``day``, sorted by time."""
    return Planner(people, day, day).free(day, now)


def days_with_slots(people, now=None):
    """[(day, slots)] for the next DAYS_AHEAD days that have a free slot."""
    today = timezone.localdate(now)
    planner = Planner(people, today, today + timedelta(days=DAYS_AHEAD - 1))
    found = []
    for offset in range(DAYS_AHEAD):
        day = today + timedelta(days=offset)
        slots = planner.free(day, now)
        if slots:
            found.append((day, slots))
    return found


def upcoming(resident, now=None):
    return Appointment.objects.filter(
        resident=resident,
        status=Appointment.Status.CONFIRMED,
        end__gt=now or timezone.now(),
    ).select_related("educator")


def _order(candidates, day):
    """ "Le premier libre": the educators free at that time, least busy that day first."""
    counts = Counter(
        Appointment.objects.filter(
            educator__in=[slot.educator for slot in candidates],
            status=Appointment.Status.CONFIRMED,
            start__date=day,
        ).values_list("educator_id", flat=True)
    )
    return sorted(candidates, key=lambda slot: (counts[slot.educator.pk], slot.educator.pk))


def _lock(people):
    """Lock users in a fixed order (by id): two bookings never wait for each other in a circle."""
    ids = sorted(person.pk for person in people)
    list(User.objects.select_for_update().filter(pk__in=ids).order_by("pk"))


def book(resident, start, people, reason="", now=None):
    """Book the meeting at ``start`` with one of ``people``. Raise BookingRefused.

    Every check runs again inside the transaction, after the locks: the limit
    of the resident, their other meetings, and that the time is still offered
    (grid, absence, length, other bookings). Locks: the resident first, then
    the educators, always in this order; a grid save locks the educator only.
    """
    now = now or timezone.now()
    if reason not in Appointment.Reason.values:
        reason = ""
    day = timezone.localtime(start).date()
    today = timezone.localdate(now)
    if not today <= day < today + timedelta(days=DAYS_AHEAD):
        raise BookingRefused("Choisissez un jour dans les deux semaines à venir.")
    candidates = [slot for slot in free_slots(people, day, now) if slot.start == start]
    if not candidates:
        raise BookingRefused(TAKEN)
    try:
        with transaction.atomic():
            _lock([resident])
            _lock([slot.educator for slot in candidates])
            if upcoming(resident, now).count() >= MAX_UPCOMING:
                raise BookingRefused(
                    f"Vous avez déjà {MAX_UPCOMING} rendez-vous à venir. "
                    "Passez à l'accueil pour en annuler un."
                )
            for slot in _order(candidates, day):
                # Still offered, now that nobody else can change it.
                still = [s for s in free_slots([slot.educator], day, now) if s.start == start]
                if not still:
                    continue  # "le premier libre": the next educator
                slot = still[0]
                if upcoming(resident, now).filter(start__lt=slot.end, end__gt=slot.start).exists():
                    raise BookingRefused("Vous avez déjà un rendez-vous à cette heure-là.")
                return Appointment.objects.create(
                    educator=slot.educator,
                    resident=resident,
                    start=slot.start,
                    end=slot.end,
                    reason=reason,
                )
            raise BookingRefused(TAKEN)
    except IntegrityError:
        raise BookingRefused("Ce créneau vient d'être pris. Choisissez-en un autre.") from None


def cancel_on_departure(sender, resident=None, **kwargs):
    """Receiver of residents.departure.departure_recorded (inside its transaction)."""
    count = Appointment.objects.filter(
        resident=resident, status=Appointment.Status.CONFIRMED, end__gt=timezone.now()
    ).update(status=Appointment.Status.CANCELLED)
    return {"appointments_cancelled": count}
