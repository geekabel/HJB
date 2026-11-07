"""Create a report (card T30)."""

from django.db import transaction
from django.utils import timezone

from housing.services import current_stay

from .models import Report, ReportEvent, ReportPhoto


class NoRoom(Exception):
    """The resident has no current stay: the report would concern no room."""


def room_of(resident):
    stay = current_stay(resident)
    return stay.room if stay else None


def create(resident, data, now=None):
    """Create the report, its photos and its first event. ``data``: the form's
    cleaned_data (photos already cleaned, see photos.py)."""
    room = room_of(resident)
    if room is None:
        raise NoRoom
    now = now or timezone.now()
    saved = []
    try:
        with transaction.atomic():
            report = Report.objects.create(
                resident=resident,
                room=room,
                category=data["category"],
                description=data["description"].strip(),
                urgency=data["urgency"],
                access_allowed=data["access"] == "yes",
                due_at=Report.due_for(data["urgency"], now),
                created_at=now,
            )
            for content, width, height in data.get("photos", []):
                photo = ReportPhoto(report=report, width=width, height=height)
                photo.image.save("photo.jpg", content, save=False)
                saved.append(photo.image.name)  # before the row: removed on error
                photo.save()
            ReportEvent.objects.create(
                report=report, author=resident, type=ReportEvent.Type.CREATED, created_at=now
            )
    except Exception:
        # The rows are rolled back: their files must not stay behind.
        for name in saved:
            ReportPhoto.image.field.storage.delete(name)
        raise
    return report


def forget_resident(resident_id, now=None):
    """Before the account of a former resident is deleted (card T36).

    The reports stay for the room's repair history, but nothing of the
    person: their text and every note are cleared, the photos (taken in
    their private room) go, and a report still open is closed (nobody can
    confirm it any more). The resident field becomes empty with the
    account (SET_NULL). Return the number of photos deleted.
    """
    now = now or timezone.now()
    reports = Report.objects.filter(resident_id=resident_id)
    _, by_model = ReportPhoto.objects.filter(report__in=reports).delete()
    still_open = list(reports.exclude(status=Report.Status.CLOSED).values_list("pk", flat=True))
    ReportEvent.objects.bulk_create(
        ReportEvent(report_id=pk, type=ReportEvent.Type.CLOSED, created_at=now) for pk in still_open
    )
    Report.objects.filter(pk__in=still_open).update(status=Report.Status.CLOSED, updated_at=now)
    ReportEvent.objects.filter(report__in=reports).update(note="")
    reports.update(description="")
    return by_model.get(ReportPhoto._meta.label, 0)
