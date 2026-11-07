"""Background tasks of the reports (card T31). Arguments are ids only.

Docs: https://docs.djangoproject.com/en/6.1/topics/tasks/
The notification says the step, never the description (locked screens).
A planned visit where the resident must be present also goes by SMS to a
resident without the application.
"""

from django.tasks import task
from django.urls import reverse

from appointments.tasks import reach

from .models import ReportEvent


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
