"""New reports, on the "Signalements" entry of the staff menu (card T31)."""

from .models import Report


def new_reports(request):
    # A function: the template calls it only for people who handle reports.
    return {"new_reports": lambda: Report.objects.filter(status=Report.Status.NEW).count()}
