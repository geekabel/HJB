"""Reminders of the meetings (card T29), sent by run_scheduled every minute.

- The day before, from 18:00 to 21:00: by notification, or by SMS for a
  resident without the application (one SMS per meeting at most). Only for a
  meeting booked before 18:00 the day before: a later booking needs no
  reminder, and no SMS goes out at night.
- One hour before: by notification only.

Each reminder is claimed in the database and queued in the same transaction:
two runs at the same time never send it twice, and a queue failure gives the
claim back for the next minute. A reminder that is too late (the worker
stopped for hours) is skipped: the task checks the time again before it sends.
An educator can turn the reminders off (EducatorSettings).
"""

import logging
from datetime import datetime, time, timedelta

from django.db import transaction
from django.utils import timezone

from .models import Appointment, EducatorSettings

logger = logging.getLogger(__name__)

DAY_BEFORE_AT = time(18, 0)
# After 21:00, the day-before reminder is not sent any more (no SMS at night).
DAY_BEFORE_FOR = timedelta(hours=3)
# Closer than this to the meeting, the day-before reminder is not sent any more.
DAY_BEFORE_LATEST = timedelta(hours=2)
HOUR_BEFORE = timedelta(hours=1)
# Closer than this, the hour-before reminder comes too late to help.
HOUR_BEFORE_LATEST = timedelta(minutes=15)


def day_before_moment(meeting):
    day = timezone.localtime(meeting.start).date() - timedelta(days=1)
    return timezone.make_aware(datetime.combine(day, DAY_BEFORE_AT))


def gets_day_before(meeting):
    """Whether this meeting has a day-before reminder at all."""
    return meeting.created_at < day_before_moment(meeting)


def gets_hour_before(meeting):
    return meeting.created_at < meeting.start - HOUR_BEFORE


def day_before_due(meeting, now):
    moment = day_before_moment(meeting)
    return (
        gets_day_before(meeting)
        and moment <= now < moment + DAY_BEFORE_FOR
        and meeting.start > now + DAY_BEFORE_LATEST
    )


def hour_before_due(meeting, now):
    return (
        gets_hour_before(meeting) and now + HOUR_BEFORE_LATEST < meeting.start <= now + HOUR_BEFORE
    )


def _claim_and_queue(meeting, kind, now):
    """Claim the reminder and queue it, together. Return whether it is queued."""
    from .tasks import remind_task

    field = f"{kind}_sent_at"
    try:
        with transaction.atomic():
            claimed = Appointment.objects.filter(
                pk=meeting.pk, **{f"{field}__isnull": True}
            ).update(**{field: now})
            if claimed:
                remind_task.enqueue(meeting_id=meeting.pk, kind=kind)
    except Exception:  # one failure must not stop the other reminders
        logger.exception("Appointment reminder not queued")
        return False
    return bool(claimed)


def send_due(now=None):
    """Claim the reminders due now and queue them. Return how many."""
    now = now or timezone.now()
    off = EducatorSettings.objects.filter(remind_residents=False).values_list(
        "educator_id", flat=True
    )
    confirmed = Appointment.objects.filter(
        status=Appointment.Status.CONFIRMED, start__gt=now
    ).exclude(educator_id__in=off)
    count = 0
    for meeting in confirmed.filter(
        day_before_sent_at__isnull=True,
        start__gt=now + DAY_BEFORE_LATEST,
        start__lte=now + timedelta(days=2),
    ):
        if day_before_due(meeting, now):
            count += _claim_and_queue(meeting, "day_before", now)
    for meeting in confirmed.filter(
        hour_before_sent_at__isnull=True,
        start__gt=now + HOUR_BEFORE_LATEST,
        start__lte=now + HOUR_BEFORE,
    ):
        if hour_before_due(meeting, now):
            count += _claim_and_queue(meeting, "hour_before", now)
    return count
