"""Delivery receipts of the SMS (card T24).

Two ways, depending on the provider:
- OVHcloud calls our callback address at each status change (ovh_callback).
- SMSGate answers when asked: poll() asks it, every minute (run_scheduled),
  about the SMS still on their way: every 5 minutes at first, then less often.

A receipt never goes back to "En route", and "Reçu" is never replaced: it is
the strongest proof. After 48 h without news, the state becomes "Inconnu";
SMSGate is still asked every 2 hours for a week, in case the phone was off.
"""

import logging
import time
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db.models import F, Q
from django.http import Http404, HttpResponse
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from sms.providers.base import ConfigurationError, DeliveryState, SmsError
from sms.providers.base import Receipt as ProviderReceipt
from sms.providers.ovh import callback_receipt
from sms.service import active_provider, provider_named

from .models import Delivery, EarlyReceipt, Receipt

logger = logging.getLogger(__name__)

GIVE_UP_AFTER = timedelta(hours=48)
GIVE_UP_DETAIL = "Pas d'accusé de réception en 48 h."
LAST_POLL_AFTER = timedelta(days=7)  # "Inconnu" after 48 h: still asked until then
POLL_BATCH = 20  # at most per run
POLL_BUDGET = 20  # seconds per run: the other scheduled work must not wait
EARLY_RECEIPT_LIFE = timedelta(hours=1)


def poll_interval(age):
    """How often to ask about an SMS sent ``age`` ago: less and less often."""
    if age < timedelta(hours=1):
        return timedelta(minutes=5)
    if age < timedelta(hours=6):
        return timedelta(minutes=30)
    return timedelta(hours=2)


def record(deliveries, receipt, now=None):
    """Apply ``receipt`` to ``deliveries`` (a queryset). Return the rows changed."""
    now = now or timezone.now()
    detail = receipt.detail[:200]
    if receipt.state == DeliveryState.DELIVERED:
        allowed = [Receipt.PENDING, Receipt.UNKNOWN, Receipt.UNDELIVERED]
    elif receipt.state == DeliveryState.UNDELIVERED:
        allowed = [Receipt.PENDING, Receipt.UNKNOWN]
    elif receipt.state == DeliveryState.UNKNOWN:
        allowed = [Receipt.PENDING]
    elif receipt.state == DeliveryState.PENDING:
        return deliveries.filter(receipt=Receipt.PENDING).update(receipt_detail=detail)
    else:
        return 0
    return deliveries.filter(receipt__in=allowed).update(
        receipt=receipt.state, receipt_detail=detail, receipt_at=receipt.at or now
    )


def give_up(now=None):
    """No news after 48 h: "Inconnu". Return the number of SMS concerned."""
    now = now or timezone.now()
    EarlyReceipt.objects.filter(received_at__lt=now - EARLY_RECEIPT_LIFE).delete()
    return Delivery.objects.filter(
        channel=Delivery.Channel.SMS, receipt=Receipt.PENDING, sent_at__lt=now - GIVE_UP_AFTER
    ).update(receipt=Receipt.UNKNOWN, receipt_detail=GIVE_UP_DETAIL, receipt_at=now)


def _to_ask(provider_name, now):
    """SMS on their way, or "Inconnu" after 48 h but less than a week old."""
    rows = (
        Delivery.objects.filter(
            Q(receipt=Receipt.PENDING) | Q(receipt=Receipt.UNKNOWN, receipt_detail=GIVE_UP_DETAIL),
            channel=Delivery.Channel.SMS,
            status=Delivery.Status.SENT,
            sms_provider=provider_name,
            sent_at__gte=now - LAST_POLL_AFTER,
        )
        .exclude(provider_message_id="")
        .filter(
            Q(receipt_checked_at__isnull=True)
            | Q(receipt_checked_at__lt=now - poll_interval(timedelta(0)))
        )
        .order_by(F("receipt_checked_at").asc(nulls_first=True), "sent_at")
        .values_list("pk", "receipt_checked_at", "provider_message_id", "sent_at")
    )
    due = []
    for pk, last_check, message_id, sent_at in rows[: POLL_BATCH * 10]:
        if last_check is None or now - last_check >= poll_interval(now - sent_at):
            due.append((pk, last_check, message_id))
            if len(due) == POLL_BATCH:
                break
    return due


def poll(now=None):
    """Ask the provider about the SMS on their way. Return the number checked.

    Asks first, then gives up: an SMS gets a last check before "Inconnu".
    """
    now = now or timezone.now()
    checked = 0
    for provider in _pollers(now):
        checked += _ask(provider, now)
    give_up(now)
    return checked


def _pollers(now):
    """The active provider, and every other provider that still has SMS on
    their way, as long as its keys are on the server (card T37b: the
    administration may switch the service while SMS are in flight)."""
    found = {}
    try:
        active = active_provider()
        found[active.name] = active
    except SmsError:
        pass
    others = (
        Delivery.objects.filter(
            channel=Delivery.Channel.SMS,
            status=Delivery.Status.SENT,
            sent_at__gte=now - LAST_POLL_AFTER,
        )
        .exclude(sms_provider__in=[*found, ""])
        .order_by()
        .values_list("sms_provider", flat=True)
        .distinct()
    )
    for name in others:
        if name not in settings.SMS_PROVIDERS:
            continue
        try:
            found[name] = provider_named(name)
        except SmsError:
            continue
    return [p for p in found.values() if p.can_poll and not p.missing_options()]


def _ask(provider, now):
    started = time.monotonic()
    checked = 0
    for pk, last_check, message_id in _to_ask(provider.name, now):
        if time.monotonic() - started > POLL_BUDGET:
            break  # slow provider: the rest waits for the next run
        # Claim the row: two runs at the same time do not ask twice.
        if not Delivery.objects.filter(pk=pk, receipt_checked_at=last_check).update(
            receipt_checked_at=now
        ):
            continue
        try:
            receipt = provider.receipt(message_id)
        except SmsError as error:
            logger.warning("SMS receipt not available (%s): %s", provider.name, error)
            if error.temporary or isinstance(error, ConfigurationError):
                break  # down, or access refused: the same for every SMS
            continue
        checked += 1
        if receipt is not None:
            record(Delivery.objects.filter(pk=pk), receipt, now)
    return checked


# OVHcloud calls this address (set by hand in its manager: SMS, API users, callback).
# No session, no CSRF token: the secret in the address is the proof, since the
# call carries no signature. Always 200 for a known secret, so OVHcloud does
# not repeat calls about SMS that are not ours (activation codes...).
@csrf_exempt
@require_http_methods(["GET", "POST"])
def ovh_callback(request, secret):
    expected = getattr(settings, "SMS_RECEIPT_SECRET", "")
    if not expected or not constant_time_compare(secret, expected):
        raise Http404
    data = request.GET if request.method == "GET" else request.POST
    message_id = (data.get("id") or "")[:64]
    receipt = callback_receipt(data.get("ptt"))
    if message_id and receipt is not None:
        found = _by_id("ovh", message_id)
        if not record(found, receipt) and not found.exists():
            # Maybe the sending is not saved yet: kept one hour (apply_early).
            _keep_early("ovh", message_id, receipt)
    response = HttpResponse("OK", content_type="text/plain")
    response["X-Robots-Tag"] = "noindex"
    return response


def _keep_early(provider_name, message_id, receipt):
    EarlyReceipt.objects.update_or_create(
        provider=provider_name,
        message_id=message_id,
        defaults={
            "state": receipt.state,
            "detail": receipt.detail[:200],
            "received_at": timezone.now(),
        },
    )


def apply_early(delivery):
    """After saving a sent SMS: a receipt may have come before the save."""
    if delivery.receipt != Receipt.PENDING or not delivery.provider_message_id:
        return
    early = EarlyReceipt.objects.filter(
        provider=delivery.sms_provider, message_id=delivery.provider_message_id
    ).first()
    if early is None:
        return
    record(
        Delivery.objects.filter(pk=delivery.pk),
        ProviderReceipt(early.state, early.detail, early.received_at),
    )
    early.delete()


def _by_id(provider_name, message_id):
    return Delivery.objects.filter(
        channel=Delivery.Channel.SMS, sms_provider=provider_name, provider_message_id=message_id
    )


def summary(campaign):
    """Receipts of the SMS of the message (not the reminder): count per state."""
    rows = campaign.deliveries.filter(
        kind=Delivery.Kind.MESSAGE, channel=Delivery.Channel.SMS
    ).exclude(receipt="")
    counts = dict.fromkeys(Receipt.values, 0)
    for state in rows.values_list("receipt", flat=True):
        counts[state] += 1
    counts["total"] = sum(counts.values())
    return counts


@dataclass
class ToWarn:
    recipient: object
    room_number: str
    reason: str


def _reached(delivery):
    """The person got it, or may still get it (an SMS on its way)."""
    if delivery.status != Delivery.Status.SENT:
        return False
    return delivery.receipt in ("", Receipt.PENDING, Receipt.DELIVERED)


def _reason(delivery):
    if delivery.status == Delivery.Status.FAILED:
        return delivery.error or "Échec de l'envoi."
    return delivery.receipt_detail or delivery.get_receipt_display()


def to_warn(campaign):
    """People who may not have the message: nothing reached them, message or reminder.

    One line per person, with the reason of the latest problem.
    """
    deliveries = (
        campaign.deliveries.exclude(status__in=[Delivery.Status.PENDING, Delivery.Status.SENDING])
        .select_related("recipient")
        .order_by("recipient_id", "kind")  # "message" before "reminder"
    )
    people = {}
    for delivery in deliveries:
        person = people.setdefault(delivery.recipient_id, {"reached": False, "last": None})
        if _reached(delivery):
            person["reached"] = True
        else:
            person["last"] = delivery
    rows = [
        ToWarn(person["last"].recipient, person["last"].room_number, _reason(person["last"]))
        for person in people.values()
        if not person["reached"] and person["last"] is not None
    ]
    rows.sort(key=lambda row: (row.room_number or "~", row.recipient.last_name))
    return rows
