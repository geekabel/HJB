"""Create a report (card T30)."""

from django.db import transaction
from django.utils import timezone

from housing.models import Stay

from .models import Report, ReportEvent, ReportPhoto


class NoRoom(Exception):
    """The resident has no current stay: the report would concern no room."""


def room_of(resident):
    stay = Stay.objects.current().filter(resident=resident).select_related("room").first()
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
                photo.image.save("photo.jpg", content, save=True)
                saved.append(photo.image.name)
            ReportEvent.objects.create(
                report=report, author=resident, type=ReportEvent.Type.CREATED, created_at=now
            )
    except Exception:
        # The rows are rolled back: their files must not stay behind.
        for name in saved:
            ReportPhoto.image.field.storage.delete(name)
        raise
    return report
