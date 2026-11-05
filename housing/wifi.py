"""Wifi access of the rooms (card T15): record, renew, show, cut.

- Front desk and administration record the access of a room: they type the
  password given by the network, or let the application generate one.
- Only administrators can show a stored password again; every display goes
  to the audit log. The lists never contain a password.
- When a stay ends (departure, change of room), the access of the room is
  cut: it must be renewed on the network before the next resident.
"""

import secrets
import unicodedata
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from audit.models import Action
from audit.service import log_action

from . import wifi_crypto
from .models import WIFI_VALIDITY_DAYS, Room, Stay, WifiAccess

# No I, l, O, 0 or 1: nothing to confuse when the password is copied by hand.
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
GENERATED_LENGTH = 12  # about 69 bits
# Length allowed by WPA2 personal passphrases.
MIN_LENGTH = 8
MAX_LENGTH = 63


def generate_password():
    return "".join(secrets.choice(ALPHABET) for _ in range(GENERATED_LENGTH))


def suggest_username(room, person=None):
    """For example "ch312-awa": the room number, then the first name without accents."""
    base = f"ch{room.number}".lower()
    if person is not None and person.first_name:
        name = unicodedata.normalize("NFKD", person.first_name)
        name = "".join(c for c in name if c.isascii() and c.isalnum()).lower()
        if name:
            base = f"{base}-{name}"
    return base[:64]


def default_expiry(on=None):
    return (on or timezone.localdate()) + timedelta(days=WIFI_VALIDITY_DAYS)


def current_access(room):
    return room.wifi_accesses.active().first()


def end_access(room, reason):
    """Cut the active access of this room. Return the number of accesses cut (0 or 1).

    Takes the same row lock on the room as set_access(): a cut and a recording
    of the same room run one after the other, never across each other.
    """
    with transaction.atomic():
        list(Room.objects.select_for_update().filter(pk=room.pk).values_list("pk", flat=True))
        return WifiAccess.objects.filter(room=room, active=True).update(
            active=False, ended_at=timezone.now(), end_reason=reason
        )


ACCESS_CHANGED = (
    "L'accès wifi de cette chambre vient d'être modifié par une autre demande. "
    "Vérifiez la fiche avant de recommencer."
)


@sensitive_variables("password")
def set_access(
    room,
    *,
    username,
    password,
    expires_on,
    stay=None,
    replaces=None,
    generated=False,
    by=None,
    request=None,
):
    """Record a new access for this room; the previous one is cut. Return the new access.

    Checked under the room lock, so a departure or another recording at the
    same moment cannot slip in between:
    - ``stay``: this stay must still be the current one of the room;
    - ``replaces``: the access the person saw on the form (None: none). If
      another access was recorded since (double click, two staff members),
      nothing is recorded.
    Raises ValidationError (codes "no_current_stay", "access_changed").
    """
    with transaction.atomic():
        # Row lock on the room: two recordings at the same time pass one after the other.
        room = Room.objects.select_for_update().get(pk=room.pk)
        if stay is not None and not Stay.objects.current().filter(pk=stay.pk, room=room).exists():
            raise ValidationError(
                "Cette personne n'occupe plus cette chambre.", code="no_current_stay"
            )
        active = WifiAccess.objects.filter(room=room, active=True).values_list("pk", flat=True)
        if list(active) != ([replaces.pk] if replaces else []):
            raise ValidationError(ACCESS_CHANGED, code="access_changed")
        end_access(room, WifiAccess.EndReason.RENEWED)
        access = WifiAccess(
            room=room,
            username=username,
            encrypted_password=wifi_crypto.encrypt(password),
            generated=generated,
            expires_on=expires_on,
            created_by=by,
        )
        access.full_clean()
        access.save()
        log_action(
            Action.WIFI_ACCESS_SET,
            actor=by,
            target=access,
            details={
                "room": room.number,
                "expires_on": expires_on.isoformat(),
                "generated": generated,
            },
            request=request,
        )
    return access


@sensitive_variables("password")
def reveal_password(access, *, by, request=None):
    """Decrypt the password for one display, and write that display to the audit log."""
    password = wifi_crypto.decrypt(access.encrypted_password)
    log_action(
        Action.WIFI_PASSWORD_SHOWN,
        actor=by,
        target=access,
        details={"room": access.room.number},
        request=request,
    )
    return password


def cut_on_departure(sender, stay=None, **kwargs):
    """Receiver of residents.departure.departure_recorded (inside its transaction)."""
    if stay is None:
        return {"wifi_cut": 0}
    return {"wifi_cut": end_access(stay.room, WifiAccess.EndReason.DEPARTURE)}
