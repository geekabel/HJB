"""Background tasks of the reports (card T31). Arguments are ids only.

Docs: https://docs.djangoproject.com/en/6.1/topics/tasks/
The notification says the step, never the description (locked screens).
A planned visit where the resident must be present also goes by SMS to a
resident without the application.
"""

from datetime import date

from django.tasks import task
from django.urls import reverse

from appointments.tasks import push, reach

from . import reminders
from .models import Report, ReportEvent
from .staff_forms import handlers


@task
def notify_resident_task(event_id):
    event = ReportEvent.objects.filter(pk=event_id).select_related("report__resident").first()
    if event is None:
        return
    report = event.report
    number = f"Signalement n° {report.pk}"
    options = {
        "url": reverse("reports:detail", args=[report.pk]),
        "tag": f"signalement-{report.pk}",
    }
    if event.type == ReportEvent.Type.ACKNOWLEDGED:
        reach(report.resident, title=number, body="Il est pris en charge.", **options)
    elif event.type == ReportEvent.Type.SCHEDULED:
        when = report.visit_text()
        present = "" if report.access_allowed else " Soyez présent, s'il vous plaît."
        reach(
            report.resident,
            title=number,
            body=f"Intervention prévue {when}.{present}",
            sms=f"HJB : intervention dans votre chambre {when}.{present}"
            if not report.access_allowed
            else "",
            **options,
        )
    elif event.type == ReportEvent.Type.INTERVENTION:
        reach(
            report.resident,
            title=number,
            body="Intervention faite. Dites-nous si c'est réglé.",
            **options,
        )


def _plural(count, word, plural=None):
    return f"{count} {word if count <= 1 else plural or word + 's'}"


@task
def late_alert_task(report_id):
    """Tell the person in charge (else everyone who handles reports) once."""
    report = Report.objects.filter(pk=report_id).select_related("room", "assigned_to").first()
    if report is None or report.status not in Report.WAITING:
        return  # handled meanwhile
    people = list(handlers())
    if report.assigned_to in people:
        people = [report.assigned_to]
    body = (
        f"Chambre {report.room.number}, {report.get_category_display().lower()} "
        f"({report.get_urgency_display().lower()})."
    )
    for person in people:
        push(
            person,
            title="Signalement en retard",
            body=body,
            url=reverse("reports_staff:detail", args=[report.pk]),
            tag=f"signalement-retard-{report.pk}",
        )


@task
def daily_summary_task(day):
    """The morning summary to everyone who handles reports (nothing if all is 0)."""
    counts = reminders.summary_counts(date.fromisoformat(day))
    parts = []
    if counts["new"]:
        parts.append(_plural(counts["new"], "nouveau", "nouveaux"))
    if counts["late"]:
        parts.append(f"{counts['late']} en retard")
    if counts["today"]:
        parts.append(_plural(counts["today"], "intervention") + " aujourd'hui")
    if counts["done"]:
        parts.append(f"{counts['done']} à confirmer par le résident")
    if not parts:
        return
    body = " · ".join(parts) + "."
    for person in handlers():
        push(
            person,
            title="Signalements du jour",
            body=body[:1].upper() + body[1:],
            url=reverse("reports_staff:board"),
            tag=f"signalements-{day}",
        )
