"""Operations on stays, always checked with full_clean() before writing."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Stay


def current_stay(resident):
    return resident.stays.current().select_related("room__floor").first()


@transaction.atomic
def assign_room(resident, room, on=None):
    """Put the person in this room from the day ``on`` (today by default).

    - No current stay: a stay starts.
    - Current stay in another room: it ends that day and a new one
      starts (internal move).
    - Stay started the same day: we simply fix the room.
    Return the current stay.
    """
    on = on or timezone.localdate()
    current = current_stay(resident)
    if current is not None:
        if current.room_id == room.pk:
            return current
        if on < current.arrival:
            raise ValidationError(
                {"arrival": "La date est avant le début du séjour en cours."},
                code="date_before_stay",
            )
        if on == current.arrival:
            current.room = room
            current.full_clean()
            current.save()
            return current
        current.departure = on
        current.full_clean()
        current.save()
    new = Stay(resident=resident, room=room, arrival=on)
    new.full_clean()
    new.save()
    return new
