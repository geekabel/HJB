"""Delays of the reports (card T32), run every minute by run_scheduled.

- A report still waiting (new, or taken but not planned) after its due date
  (4 h urgent, 48 h annoying, 7 days can wait) is late: the person in charge
  is told once, or everyone who handles reports when nobody took it.
- A report done 3 days ago without an answer of the resident is closed
  (card T33).
- Every morning at 9:00, a summary goes to the team: new reports, late ones,
  visits of the day, work waiting for the resident's confirmation. Nothing is
  sent on a day with nothing to say. A summary not sent by noon (worker
  stopped) is skipped: it would be stale.

Each alert is claimed in the database and queued in the same transaction,
as for the meeting reminders (appointments/reminders.py): two runs at the
same time never send it twice.
"""

import logging
from datetime import datetime, time

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import DailySummary, Report

logger = logging.getLogger(__name__)

SUMMARY_FROM = time(9, 0)
SUMMARY_UNTIL = time(12, 0)


def _alert_late(report_id, now):
    from .tasks import late_alert_task

    try:
        with transaction.atomic():
            claimed = Report.objects.filter(
                pk=report_id, late_alerted_at__isnull=True, status__in=Report.WAITING
            ).update(late_alerted_at=now)
            if claimed:
                late_alert_task.enqueue(report_id=report_id)
    except Exception:  # one failure must not stop the other alerts
        logger.exception("Late report alert not queued")
        return False
    return bool(claimed)


def _summary(now):
    from .tasks import daily_summary_task

    local = timezone.localtime(now)
    if not SUMMARY_FROM <= local.time() < SUMMARY_UNTIL:
        return False
    try:
        with transaction.atomic():
            DailySummary.objects.create(day=local.date(), sent_at=now)
            daily_summary_task.enqueue(day=local.date().isoformat())
    except IntegrityError:
        return False  # already sent today
    except Exception:
        logger.exception("Daily report summary not queued")
        return False
    return True


def send_due(now=None):
    """Claim the alerts due now and queue them. Return how many."""
    now = now or timezone.now()
    late = Report.objects.filter(
        status__in=Report.WAITING, due_at__lte=now, late_alerted_at__isnull=True
    ).values_list("pk", flat=True)
    count = sum(_alert_late(pk, now) for pk in late)
    from .handling import close_unanswered

    try:
        count += close_unanswered(now)
    except Exception:
        logger.exception("Done reports not closed")
    return count + _summary(now)


def summary_counts(day, now=None):
    """What the morning summary says, for ``day`` (a date)."""
    now = now or timezone.now()
    start = timezone.make_aware(datetime.combine(day, time.min))
    end = timezone.make_aware(datetime.combine(day, time.max))
    waiting = Report.objects.filter(status__in=Report.WAITING)
    return {
        # A late new report counts once, as late.
        "new": Report.objects.filter(status=Report.Status.NEW, due_at__gt=now).count(),
        "late": waiting.filter(due_at__lte=now).count(),
        "today": Report.objects.filter(
            status=Report.Status.SCHEDULED, intervention_start__range=(start, end)
        ).count(),
        "done": Report.objects.filter(status=Report.Status.DONE).count(),
    }
