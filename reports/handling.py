"""The staff handle a report (card T31): take it, plan the visit, mark it done.

Each step changes the status under a row lock (two people pressing "Je m'en
occupe" at once: the second one is told), writes a ReportEvent (the history,
shown to the resident in T33) and tells the resident, after the commit.

    new ── take ──> acknowledged ── plan ──> scheduled ── done ──> done
     │                   └────────────── done ──────────────────┘
     └── plan or done directly (the staff went at once)
A planned visit can be moved (plan again). Giving the report to someone
else is written in the history, without telling the resident.

The resident follows (card T33): "C'est réglé" closes a done report; "Pas
encore" opens it again (acknowledged, a new due date from now); "Relancer"
reminds the team 48 h after the last step. Without an answer, a done report
closes on its own after 3 days (reminders.py).
"""

from django.db import transaction
from django.utils import timezone

from .models import Report, ReportEvent


class StepRefused(Exception):
    """The report is no longer in a state that allows this step."""


def _locked(report):
    return Report.objects.select_for_update().get(pk=report.pk)


def _event(report, by, kind, note="", now=None, tell=True):
    event = ReportEvent.objects.create(
        report=report, author=by, type=kind, note=note.strip(), created_at=now or timezone.now()
    )
    if tell:
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
    name = assignee.get_full_name() or assignee.get_username()
    _event(report, by, ReportEvent.Type.ASSIGNED, f"À {name}", tell=False)
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
    report.done_at = timezone.now()
    report.save(update_fields=["status", "assigned_to", "done_at", "updated_at"])
    _event(report, by, ReportEvent.Type.INTERVENTION, note)
    return report


def _tell_team(report, title):
    """Tell the person in charge, else everyone who handles reports (card T33)."""
    from .tasks import team_alert_task

    transaction.on_commit(lambda: team_alert_task.enqueue(report_id=report.pk, title=title))


@transaction.atomic
def confirm(report, resident):
    """The resident says it is fixed: the report is closed."""
    report = _locked(report)
    if report.status != Report.Status.DONE:
        raise StepRefused("Ce signalement n'attend pas votre réponse.")
    report.status = Report.Status.CLOSED
    report.save(update_fields=["status", "updated_at"])
    _event(report, resident, ReportEvent.Type.CONFIRMED, tell=False)
    return report


@transaction.atomic
def reopen(report, resident, note=""):
    """Not fixed yet: back to the team, with a new due date from now."""
    report = _locked(report)
    if report.status != Report.Status.DONE:
        raise StepRefused("Ce signalement n'attend pas votre réponse.")
    now = timezone.now()
    report.status = Report.Status.ACKNOWLEDGED
    report.due_at = Report.due_for(report.urgency, now)
    report.late_alerted_at = None  # the new due date can be late again (T32)
    report.done_at = None
    report.save(update_fields=["status", "due_at", "late_alerted_at", "done_at", "updated_at"])
    _event(report, resident, ReportEvent.Type.REOPENED, note, now=now, tell=False)
    _tell_team(report, "Pas encore réglé")
    return report


@transaction.atomic
def remind(report, resident):
    """The resident reminds the team, at most every 48 h."""
    report = _locked(report)
    start = report.can_remind_from()
    now = timezone.now()
    if start is None or now < start:
        raise StepRefused("Vous pourrez relancer l'équipe un peu plus tard.")
    _event(report, resident, ReportEvent.Type.REMINDER, now=now, tell=False)
    _tell_team(report, "Relance du résident")
    return report


def close_unanswered(now=None):
    """Close the done reports without an answer for 3 days. Return how many."""
    now = now or timezone.now()
    closed = 0
    for pk in Report.objects.filter(
        status=Report.Status.DONE, done_at__lte=now - Report.CLOSE_AFTER
    ).values_list("pk", flat=True):
        with transaction.atomic():
            report = Report.objects.select_for_update().get(pk=pk)
            if report.status != Report.Status.DONE:
                continue
            report.status = Report.Status.CLOSED
            report.save(update_fields=["status", "updated_at"])
            ReportEvent.objects.create(
                report=report,
                type=ReportEvent.Type.CLOSED,
                note="Sans réponse pendant 3 jours.",
                created_at=now,
            )
            closed += 1
    return closed
