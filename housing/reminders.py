"""Reminder before the end of a wifi access (card T17).

Run every day by the scheduler of the server:

    python manage.py send_wifi_reminders

The resident of the room gets one notification WIFI_REMINDER_DAYS days before
the end of the access (or later, if the command did not run on that day). It
is marked as sent only when it reached at least one device: a resident who
turns notifications on later, before the end, still gets it.
"""

from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Prefetch
from django.utils import timezone

from push.services import send_to_user

from .models import WIFI_REMINDER_DAYS, Stay, WifiAccess


@dataclass
class ReminderResult:
    sent: int = 0
    reminder_off: int = 0  # the resident turned the reminder off
    not_delivered: int = 0  # no device, or no device reached


def due(today=None):
    """Active accesses that end within WIFI_REMINDER_DAYS and have no reminder yet."""
    today = today or timezone.localdate()
    current = Stay.objects.current().select_related("resident")
    return (
        WifiAccess.objects.active()
        .filter(
            reminder_sent_at__isnull=True,
            expires_on__gte=today,
            expires_on__lte=today + timedelta(days=WIFI_REMINDER_DAYS),
        )
        .select_related("room")
        .prefetch_related(Prefetch("room__stays", queryset=current, to_attr="current_stays"))
        .order_by("expires_on")
    )


def message(access, today=None):
    days = (access.expires_on - (today or timezone.localdate())).days
    when = "aujourd'hui" if days == 0 else ("demain" if days == 1 else f"dans {days} jours")
    return (
        "Votre wifi se termine bientôt",
        f"Votre accès wifi se termine {when}, le {access.expires_on:%d/%m}. "
        "Passez à l'accueil pour le renouveler.",
    )


def send_wifi_reminders(today=None):
    today = today or timezone.localdate()
    result = ReminderResult()
    for access in due(today):
        if not access.room.current_stays:
            continue  # cut at departure anyway; nothing to remind
        resident = access.room.current_stays[0].resident
        if not resident.wifi_expiry_reminder:
            result.reminder_off += 1
            continue
        title, body = message(access, today)
        sent = send_to_user(resident, title=title, body=body, url="/wifi/", tag="wifi-expiry")
        if sent.sent:
            access.reminder_sent_at = timezone.now()
            access.save(update_fields=["reminder_sent_at"])
            result.sent += 1
        else:
            result.not_delivered += 1
    return result
