"""Departure of a resident: stay ended, account disabled, sessions closed, audit entry.

Django docs:
- signals: https://docs.djangoproject.com/en/6.1/topics/signals/#defining-and-sending-signals
- database sessions: https://docs.djangoproject.com/en/6.1/topics/http/sessions/#using-database-backed-sessions
- ModelBackend refuses an inactive account (user_can_authenticate):
  https://docs.djangoproject.com/en/6.1/ref/contrib/auth/#django.contrib.auth.backends.ModelBackend
"""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.dispatch import Signal
from django.utils import timezone

from accounts.models import ActivationCode
from accounts.sessions import close_sessions, session_keys_for
from audit.models import Action
from audit.service import log_action
from housing.services import current_stay

# Sent inside the departure transaction, with resident, stay (or None) and on.
# Cards T13 (passkeys, access/signals.py) and T15 (wifi) connect to it:
# if one of them fails, the whole departure is rolled back.
departure_recorded = Signal()


def has_left(resident):
    """Account disabled and no current stay: the departure is already done.

    An account disabled elsewhere (admin site) but still housed can still
    get its departure, to free the room.
    """
    return not resident.is_active and current_stay(resident) is None


def check_date(on, stay):
    """Possible errors on the departure date, in plain words."""
    if on > timezone.localdate():
        raise ValidationError(
            "La date ne peut pas être dans le futur. Enregistrez le départ le jour même.",
            code="departure_in_future",
        )
    if stay and on < stay.arrival:
        raise ValidationError(
            f"La date est avant l'arrivée dans la chambre ({stay.arrival:%d/%m/%Y}).",
            code="departure_before_arrival",
        )


def record_departure(resident, on, *, request=None):
    """Record the departure. All or nothing. Return the ended stay (or None)."""
    # Read the sessions before the transaction: it can be slow and
    # does not need the write lock.
    keys = session_keys_for(resident)
    with transaction.atomic():
        # Row lock: two departures, or a departure and a profile change,
        # cannot overlap.
        resident = type(resident).objects.select_for_update().get(pk=resident.pk)
        if has_left(resident):
            raise ValidationError(
                "Le départ de cette personne est déjà enregistré.", code="already_left"
            )
        stay = current_stay(resident)
        check_date(on, stay)
        if stay:
            stay.departure = on
            stay.full_clean()
            stay.save(update_fields=["departure"])

        # An activation code that is still valid must no longer work.
        ActivationCode.objects.valid().filter(user=resident).update(cancelled_at=timezone.now())
        resident.is_active = False
        # This also changes the session hash: any remaining session becomes invalid.
        resident.set_unusable_password()
        resident.save(update_fields=["is_active", "password"])

        # Each receiver can return a dict, added to the audit details
        # (for example the number of passkeys removed).
        responses = departure_recorded.send(
            sender=resident.__class__, resident=resident, stay=stay, on=on
        )
        sessions = close_sessions(keys)
        details = {
            "room": stay.room.number if stay else "",
            "departure": on.isoformat(),
            "sessions_closed": sessions,
        }
        for _receiver, response in responses:
            if isinstance(response, dict):
                details.update(response)
        log_action(Action.RESIDENT_DEPARTED, target=resident, details=details, request=request)
    return stay


def record_return(resident, room, on, *, request=None):
    """Return of a former resident: account enabled again and new stay. All or nothing.

    The person must then get a new activation code at the front desk.
    """
    from housing.services import assign_room

    with transaction.atomic():
        resident = type(resident).objects.select_for_update().get(pk=resident.pk)
        if not has_left(resident):
            raise ValidationError("Cette personne n'est pas partie.", code="not_left")
        if on > timezone.localdate():
            raise ValidationError(
                "La date ne peut pas être dans le futur.", code="return_in_future"
            )
        resident.is_active = True
        # The account must be activated again (code, phone, passkey):
        # otherwise it would look "activated" because of the old login.
        resident.last_login = None
        resident.verified_phone = ""
        resident.phone_verified_at = None
        resident.save(
            update_fields=["is_active", "last_login", "verified_phone", "phone_verified_at"]
        )
        # No old passkey may survive the return (they are removed at
        # departure; this covers a passkey created at the last moment).
        from access.credentials import remove_all

        remove_all(resident)
        stay = assign_room(resident, room, on)
        log_action(
            Action.RESIDENT_RETURNED,
            target=resident,
            details={"room": room.number, "arrival": on.isoformat()},
            request=request,
        )
    return stay


PLANNED_LIMIT_DAYS = 365


def plan_departure(resident, on, *, by, request=None):
    """Departure typed in advance (card T21): recorded on that day at noon by run_scheduled."""
    with transaction.atomic():
        resident = type(resident).objects.select_for_update().get(pk=resident.pk)
        stay = current_stay(resident)
        if stay is None:
            raise ValidationError(
                "Sans chambre, le départ s'enregistre le jour même.", code="no_stay"
            )
        if on > timezone.localdate() + timedelta(days=PLANNED_LIMIT_DAYS):
            raise ValidationError("La date est à plus d'un an.", code="too_far")
        if on <= timezone.localdate():
            raise ValidationError("Un départ prévu est dans le futur.", code="not_future")
        if on < stay.arrival:
            raise ValidationError(
                f"La date est avant l'arrivée dans la chambre ({stay.arrival:%d/%m/%Y}).",
                code="departure_before_arrival",
            )
        stay.planned_departure = on
        stay.save(update_fields=["planned_departure"])
        log_action(
            Action.DEPARTURE_PLANNED,
            actor=by,
            target=resident,
            details={"room": stay.room.number, "planned_departure": on.isoformat()},
            request=request,
        )
    return stay


def cancel_planned_departure(resident, *, by, request=None):
    with transaction.atomic():
        stay = current_stay(resident)
        if stay is None or stay.planned_departure is None:
            return False
        planned = stay.planned_departure
        stay.planned_departure = None
        stay.save(update_fields=["planned_departure"])
        log_action(
            Action.DEPARTURE_PLAN_CANCELLED,
            actor=by,
            target=resident,
            details={"room": stay.room.number, "planned_departure": planned.isoformat()},
            request=request,
        )
    return True
