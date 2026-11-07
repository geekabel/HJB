"""The staff handle a report (card T31): take it, plan the visit, mark it done.

Each step changes the status under a row lock (two people pressing "Je m'en
occupe" at once: the second one is told), writes a ReportEvent (the history,
shown to the resident in T33) and tells the resident, after the commit.

    new ── take ──> acknowledged ── plan ──> scheduled ── done ──> done
                         └────────────── done ──────────────────┘
A planned visit can be moved (plan again). Closing comes with T33.
"""

from django.db import transaction
from django.utils import timezone

from .models import Report, ReportEvent


class StepRefused(Exception):
    """The report is no longer in a state that allows this step."""


def _locked(report):
    return Report.objects.select_for_update().get(pk=report.pk)


def _event(report, by, kind, note="", now=None):
    event = ReportEvent.objects.create(
        report=report, author=by, type=kind, note=note.strip(), created_at=now or timezone.now()
    )
    from .tasks import notify_resident_task

    transaction.on_commit(lambda: notify_resident_task.enqueue(event_id=event.pk))
    return event


@transaction.atomic
def take(report, by, assignee=None):
    """Take a new report in hand, for ``assignee`` (the person by default)."""
    report = _locked(report)
    if report.status != Report.Status.NEW:
        raise StepRefused("Ce signalement est déjà pris en charge.")
    report.status = Report.Status.ACKNOWLEDGED
    report.assigned_to = assignee or by
    report.save(update_fields=["status", "assigned_to", "updated_at"])
    _event(report, by, ReportEvent.Type.ACKNOWLEDGED)
    return report


@transaction.atomic
def assign(report, by, assignee):
    """Give the report to someone else. The resident is not told."""
    report = _locked(report)
    if report.status not in (
        Report.Status.NEW,
        Report.Status.ACKNOWLEDGED,
        Report.Status.SCHEDULED,
    ):
        raise StepRefused("Ce signalement est terminé.")
    if report.status == Report.Status.NEW:
        return take(report, by, assignee)
    report.assigned_to = assignee
    report.save(update_fields=["assigned_to", "updated_at"])
    return report


@transaction.atomic
def plan(report, by, start, end, note=""):
    """Plan the visit (or move it). The resident is told the time."""
    if end <= start:
        raise StepRefused("L'heure de fin doit être après le début.")
    report = _locked(report)
    if report.status not in (
        Report.Status.NEW,
        Report.Status.ACKNOWLEDGED,
        Report.Status.SCHEDULED,
    ):
        raise StepRefused("Ce signalement est terminé.")
    report.status = Report.Status.SCHEDULED
    report.assigned_to = report.assigned_to or by
    report.intervention_start, report.intervention_end = start, end
    report.save(
        update_fields=[
            "status",
            "assigned_to",
            "intervention_start",
            "intervention_end",
            "updated_at",
        ]
    )
    _event(report, by, ReportEvent.Type.SCHEDULED, note)
    return report


@transaction.atomic
def done(report, by, note=""):
    """The work is done: the resident is asked to confirm (T33)."""
    report = _locked(report)
    if report.status not in (
        Report.Status.NEW,
        Report.Status.ACKNOWLEDGED,
        Report.Status.SCHEDULED,
    ):
        raise StepRefused("Ce signalement est déjà marqué comme fait.")
    report.status = Report.Status.DONE
    report.assigned_to = report.assigned_to or by
    report.save(update_fields=["status", "assigned_to", "updated_at"])
    _event(report, by, ReportEvent.Type.INTERVENTION, note)
    return report
