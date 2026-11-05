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

from django.db import transaction
from django.utils import timezone

from audit.models import Action
from audit.service import log_action

from . import wifi_crypto
from .models import WIFI_VALIDITY_DAYS, Room, WifiAccess

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
    """Cut the active access of this room. Return the number of accesses cut (0 or 1)."""
    return WifiAccess.objects.filter(room=room, active=True).update(
        active=False, ended_at=timezone.now(), end_reason=reason
    )


def set_access(room, *, username, password, expires_on, generated=False, by=None, request=None):
    """Record a new access for this room; the previous one is cut. Return the new access."""
    with transaction.atomic():
        # Row lock on the room: two recordings at the same time pass one after the other.
        room = Room.objects.select_for_update().get(pk=room.pk)
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
