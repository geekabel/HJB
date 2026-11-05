"""Weekly grid of an educator and the times a resident can book (card T26).

The grid has one cell per half hour, from 8:00 to 19:00, Monday to Friday.
Open cells that touch are saved as one range (Availability). The bookable
times cut each range into meetings of the educator's length, after the
booking deadline.

save_grid() deletes and recreates the rows of the educator: nothing may point
to an Availability row (a booked meeting keeps its own start and end).
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.contrib.auth import get_user_model
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


# The only keys accepted: other spellings of a cell ("00-1000") are refused.
CELLS = {cell_key(day, moment): (day, moment) for day in DAYS for moment in cell_times()}


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
    cells = sorted({CELLS[key] for key in keys if key in CELLS})
    merged = {}
    for weekday, start in cells:
        day = merged.setdefault(weekday, [])
        if day and day[-1][1] == start:
            day[-1] = (day[-1][0], _add(start, STEP))
        else:
            day.append((start, _add(start, STEP)))
    return merged


def lock(educator):
    """Lock the educator row until the end of the transaction.

    The grid save and the bookings of this educator (T27) then run one after
    the other (PostgreSQL; SQLite runs its writing transactions one by one).
    """
    get_user_model().objects.select_for_update().filter(pk=educator.pk).first()


@transaction.atomic
def save_grid(educator, keys):
    """Replace the weekly grid of ``educator``. Return the number of ranges."""
    lock(educator)
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
    now = now or timezone.now()
    if settings.notice == EducatorSettings.Notice.DAY_BEFORE:
        tomorrow = timezone.localdate(now) + timedelta(days=1)
        return timezone.make_aware(datetime.combine(tomorrow, time(0, 0)))
    # Real time, not clock time: 2 hours are 2 hours across a clock change.
    return now + timedelta(hours=2)


def too_short(educator, minutes):
    """Ranges of ``educator`` shorter than a meeting: they give no slot."""
    length = timedelta(minutes=minutes)
    return [
        row
        for row in Availability.objects.filter(educator=educator)
        if datetime.combine(date.min, row.end) - datetime.combine(date.min, row.start) < length
    ]


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
