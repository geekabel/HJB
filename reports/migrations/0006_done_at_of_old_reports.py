"""Reports marked done before done_at existed (card T33, review): their done
date is the last "Intervention faite" step, so they close on their own too."""

from django.db import migrations


def fill_done_at(apps, schema_editor):
    Report = apps.get_model("reports", "Report")
    ReportEvent = apps.get_model("reports", "ReportEvent")
    for report in Report.objects.filter(status="done", done_at__isnull=True):
        last = (
            ReportEvent.objects.filter(report=report, type="intervention")
            .order_by("-created_at")
            .values_list("created_at", flat=True)
            .first()
        )
        report.done_at = last or report.updated_at
        report.save(update_fields=["done_at"])


class Migration(migrations.Migration):
    dependencies = [("reports", "0005_follow_up")]

    operations = [migrations.RunPython(fill_done_at, migrations.RunPython.noop)]
