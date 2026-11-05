"""Operations on stays, always checked with full_clean() before writing."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Stay, WifiAccess
from .wifi import end_access


def current_stay(resident):
    return resident.stays.current().select_related("room__floor").first()


@transaction.atomic
def assign_room(resident, room, on=None):
    """Put the person in this room from the day ``on`` (today by default).

    - No current stay: a stay starts.
    - Current stay in another room: it ends that day and a new one
      starts (internal move). The wifi access of the old room is cut.
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
            # Same day: the room is corrected. The person may already know the
            # wifi of the first room, so it is cut too (T15).
            old_room = current.room
            current.room = room
            current.full_clean()
            current.save()
            end_access(old_room, WifiAccess.EndReason.MOVE)
            return current
        current.departure = on
        current.full_clean()
        current.save()
        # The person leaves this room: its wifi access must be renewed (T15).
        end_access(current.room, WifiAccess.EndReason.MOVE)
    # A departure planned in advance (card T21) still holds after a move.
    planned = current.planned_departure if current is not None else None
    new = Stay(
        resident=resident,
        room=room,
        arrival=on,
        planned_departure=planned if planned and planned > on else None,
    )
    new.full_clean()
    new.save()
    return new
