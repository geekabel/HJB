"""Weekly grid of an educator and the times a resident can book (card T26).

The grid has one cell per half hour, from 8:00 to 19:00, Monday to Friday.
Open cells that touch are saved as one range (Availability). The bookable
times cut each range into meetings of the educator's length, after the
booking deadline.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.db import transaction
from django.utils import timezone

from .models import Availability, EducatorSettings

DAYS = (0, 1, 2, 3, 4)  # Monday to Friday
FIRST = time(8, 0)
LAST = time(19, 0)
STEP = timedelta(minutes=30)


def cell_times():
    """Start of each half-hour cell: 8:00, 8:30, ..., 18:30."""
    moment = datetime.combine(date.min, FIRST)
    end = datetime.combine(date.min, LAST)
    times = []
    while moment < end:
        times.append(moment.time())
        moment += STEP
    return times


def cell_key(weekday, start):
    return f"{weekday}-{start:%H%M}"


def _parse(key):
    try:
        weekday, hhmm = key.split("-")
        weekday = int(weekday)
        start = time(int(hhmm[:2]), int(hhmm[2:]))
    except (ValueError, TypeError):
        return None
    if weekday not in DAYS or start not in cell_times():
        return None
    return weekday, start


def _add(moment, delta):
    return (datetime.combine(date.min, moment) + delta).time()


def open_cells(educator):
    """Keys of the open cells of ``educator``."""
    keys = set()
    for availability in Availability.objects.filter(educator=educator):
        moment = availability.start
        while moment < availability.end:
            keys.add(cell_key(availability.weekday, moment))
            following = _add(moment, STEP)
            if following <= moment:  # past midnight: never in the grid
                break
            moment = following
    return keys


def ranges(keys):
    """{weekday: [(start, end), ...]} from cell keys, cells that touch merged."""
    cells = sorted(filter(None, (_parse(key) for key in keys)))
    merged = {}
    for weekday, start in cells:
        day = merged.setdefault(weekday, [])
        if day and day[-1][1] == start:
            day[-1] = (day[-1][0], _add(start, STEP))
        else:
            day.append((start, _add(start, STEP)))
    return merged


@transaction.atomic
def save_grid(educator, keys):
    """Replace the weekly grid of ``educator``. Return the number of ranges."""
    Availability.objects.filter(educator=educator).delete()
    rows = [
        Availability(educator=educator, weekday=weekday, start=start, end=end)
        for weekday, day in ranges(keys).items()
        for start, end in day
    ]
    Availability.objects.bulk_create(rows)
    return len(rows)


def settings_of(educator):
    """The settings of ``educator`` (the defaults if never saved)."""
    found = EducatorSettings.objects.filter(educator=educator).first()
    return found or EducatorSettings(educator=educator)


def earliest_start(settings, now=None):
    """The first moment a resident can still book."""
    now = timezone.localtime(now or timezone.now())
    if settings.notice == EducatorSettings.Notice.DAY_BEFORE:
        tomorrow = now.date() + timedelta(days=1)
        return timezone.make_aware(datetime.combine(tomorrow, time(0, 0)))
    return now + timedelta(hours=2)


@dataclass(frozen=True)
class Slot:
    educator: object
    start: datetime
    end: datetime


def bookable(educator, day, now=None, settings=None, availabilities=None):
    """Meetings that ``educator`` offers on ``day``, after the booking deadline."""
    settings = settings or settings_of(educator)
    length = timedelta(minutes=settings.slot_minutes)
    earliest = earliest_start(settings, now)
    if availabilities is None:
        availabilities = Availability.objects.filter(educator=educator, weekday=day.weekday())
    slots = []
    for availability in availabilities:
        if availability.weekday != day.weekday():
            continue
        start = timezone.make_aware(datetime.combine(day, availability.start))
        end_of_range = timezone.make_aware(datetime.combine(day, availability.end))
        while start + length <= end_of_range:
            if start >= earliest:
                slots.append(Slot(educator, start, start + length))
            start += length
    return slots
