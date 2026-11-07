"""Reminder before the end of a wifi access (card T17).

Run every day by the scheduler of the server:

    python manage.py send_wifi_reminders

The resident of the room gets one notification WIFI_REMINDER_DAYS days before
the end of the access (or later, if the command did not run on that day). It
is marked as sent only when it reached at least one device: a resident who
turns notifications on later, before the end, still gets it.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone
from django.utils.formats import date_format

from push.services import send_to_user

from .models import WIFI_REMINDER_DAYS, Stay, WifiAccess

logger = logging.getLogger(__name__)


@dataclass
class ReminderResult:
    sent: int = 0
    reminder_off: int = 0  # the resident turned the reminder off
    not_delivered: int = 0  # no device, or no device reached


def due(today=None):
    """Active accesses that end within WIFI_REMINDER_DAYS and have no reminder yet."""
    today = today or timezone.localdate()
    return (
        WifiAccess.objects.active()
        .filter(
            reminder_sent_at__isnull=True,
            expires_on__gte=today,
            expires_on__lte=today + timedelta(days=WIFI_REMINDER_DAYS),
        )
        .select_related("room")
        .order_by("expires_on")
    )


def message(access, today=None):
    days = (access.expires_on - (today or timezone.localdate())).days
    when = "aujourd'hui" if days == 0 else ("demain" if days == 1 else f"dans {days} jours")
    return (
        "Votre wifi se termine bientôt",
        f"Votre accès wifi se termine {when}, le {date_format(access.expires_on, 'j F')}. "
        "Passez à l'accueil pour le renouveler.",
    )


def _claim(access):
    """Mark the reminder as sent before sending: a second run at the same time skips it."""
    return WifiAccess.objects.filter(
        pk=access.pk, active=True, reminder_sent_at__isnull=True
    ).update(reminder_sent_at=timezone.now())


def send_wifi_reminders(today=None):
    today = today or timezone.localdate()
    result = ReminderResult()
    for access in due(today):
        if not _claim(access):
            continue  # sent by another run, renewed or cut since the list was read
        try:
            # Read again after the claim: a room change or a departure may have happened.
            stay = (
                Stay.objects.current().filter(room=access.room).select_related("resident").first()
            )
            delivered = False
            if stay is None:
                pass  # cut at departure anyway: nothing to remind
            elif not stay.resident.wifi_expiry_reminder:
                result.reminder_off += 1
            else:
                title, body = message(access, today)
                sent = send_to_user(
                    stay.resident, title=title, body=body, url="/wifi/", tag="wifi-expiry"
                )
                delivered = bool(sent.sent)
                if delivered:
                    result.sent += 1
                else:
                    result.not_delivered += 1
        except Exception:
            # One error must not stop the reminders of the other residents.
            logger.exception("Wifi reminder failed for access %s", access.pk)
            delivered = False
        if not delivered:
            # Not reached (reminder off, no device, error): free it for the next run.
            WifiAccess.objects.filter(pk=access.pk).update(reminder_sent_at=None)
    return result
