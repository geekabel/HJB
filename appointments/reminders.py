"""Reminders of the meetings (card T29), sent by run_scheduled every minute.

- The day before, at 18:00: by notification, or by SMS for a resident without
  the application (one SMS per meeting at most).
- One hour before: by notification only.

Each reminder is claimed in the database before it leaves (a conditional
update), so two runs at the same time never send it twice. A reminder that is
too late (the worker stopped for hours) is skipped: never sent after the moment
it was meant for. An educator can turn the reminders off (EducatorSettings).
"""

from datetime import datetime, time, timedelta

from django.utils import timezone

from .models import Appointment, EducatorSettings

DAY_BEFORE_AT = time(18, 0)
HOUR_BEFORE = timedelta(hours=1)
# Closer than this to the meeting, the day-before reminder is not sent any more.
DAY_BEFORE_LATEST = timedelta(hours=2)


def day_before_moment(meeting):
    day = timezone.localtime(meeting.start).date() - timedelta(days=1)
    return timezone.make_aware(datetime.combine(day, DAY_BEFORE_AT))


def _claim(meeting, field, now):
    return Appointment.objects.filter(pk=meeting.pk, **{f"{field}__isnull": True}).update(
        **{field: now}
    )


def send_due(now=None):
    """Claim the reminders due now and queue them. Return how many."""
    from .tasks import remind_task

    now = now or timezone.now()
    off = EducatorSettings.objects.filter(remind_residents=False).values_list(
        "educator_id", flat=True
    )
    confirmed = Appointment.objects.filter(
        status=Appointment.Status.CONFIRMED, start__gt=now
    ).exclude(educator_id__in=off)
    due = []
    # The day before at 18:00, while the meeting is more than 2 hours away.
    for meeting in confirmed.filter(
        day_before_sent_at__isnull=True,
        start__gt=now + DAY_BEFORE_LATEST,
        start__lte=now + timedelta(days=2),
    ):
        if day_before_moment(meeting) <= now and _claim(meeting, "day_before_sent_at", now):
            due.append((meeting.pk, "day_before"))
    # One hour before.
    for meeting in confirmed.filter(hour_before_sent_at__isnull=True, start__lte=now + HOUR_BEFORE):
        if _claim(meeting, "hour_before_sent_at", now):
            due.append((meeting.pk, "hour_before"))
    for pk, kind in due:
        remind_task.enqueue(meeting_id=pk, kind=kind)
    return len(due)
