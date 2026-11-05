"""Delivery receipts of the SMS (card T24).

Two ways, depending on the provider:
- OVHcloud calls our callback address at each status change (ovh_callback).
- SMSGate answers when asked: poll() asks it, every minute (run_scheduled),
  for the SMS still on their way, each one at most every 5 minutes.

A receipt never goes back: once "Reçu" or "Non reçu", a late "En route" is
ignored. After 48 h without news, the state becomes "Inconnu".
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.db.models import F, Q
from django.http import Http404, HttpResponse
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from sms.providers.base import DeliveryState, SmsError
from sms.providers.ovh import callback_receipt
from sms.service import active_provider

from .models import Delivery, Receipt

logger = logging.getLogger(__name__)

POLL_EVERY = timedelta(minutes=5)
GIVE_UP_AFTER = timedelta(hours=48)
POLL_BATCH = 20  # at most per minute: the run stays short


def _waiting(provider_name):
    return Delivery.objects.filter(
        channel=Delivery.Channel.SMS,
        status=Delivery.Status.SENT,
        receipt=Receipt.PENDING,
        sms_provider=provider_name,
    ).exclude(provider_message_id="")


def record(deliveries, receipt, now=None):
    """Apply ``receipt`` to ``deliveries`` (a queryset). Return the rows changed."""
    now = now or timezone.now()
    detail = receipt.detail[:200]
    if receipt.state in DeliveryState.FINAL:
        # A real answer may still replace "Inconnu" (the 48 h limit).
        allowed = [Receipt.PENDING, Receipt.UNKNOWN]
        if receipt.state == DeliveryState.UNKNOWN:
            allowed = [Receipt.PENDING]
        return deliveries.filter(receipt__in=allowed).update(
            receipt=receipt.state, receipt_detail=detail, receipt_at=receipt.at or now
        )
    if receipt.state == DeliveryState.PENDING:
        return deliveries.filter(receipt=Receipt.PENDING).update(receipt_detail=detail)
    return 0


def give_up(now=None):
    """No news after 48 h: "Inconnu". Return the number of SMS concerned."""
    now = now or timezone.now()
    return Delivery.objects.filter(
        channel=Delivery.Channel.SMS, receipt=Receipt.PENDING, sent_at__lt=now - GIVE_UP_AFTER
    ).update(
        receipt=Receipt.UNKNOWN,
        receipt_detail="Pas d'accusé de réception en 48 h.",
        receipt_at=now,
    )


def poll(now=None):
    """Ask the provider about the SMS on their way. Return the number checked."""
    now = now or timezone.now()
    give_up(now)
    try:
        provider = active_provider()
    except SmsError:
        return 0
    if not provider.can_poll or provider.missing_options():
        return 0
    due = (
        _waiting(provider.name)
        .filter(Q(receipt_checked_at__isnull=True) | Q(receipt_checked_at__lt=now - POLL_EVERY))
        .order_by(F("receipt_checked_at").asc(nulls_first=True), "sent_at")
        .values_list("pk", "receipt_checked_at", "provider_message_id")[:POLL_BATCH]
    )
    checked = 0
    for pk, last_check, message_id in list(due):
        # Claim the row: two runs at the same time do not ask twice.
        if not Delivery.objects.filter(pk=pk, receipt_checked_at=last_check).update(
            receipt_checked_at=now
        ):
            continue
        try:
            receipt = provider.receipt(message_id)
        except SmsError as error:
            logger.warning("SMS receipt not available (%s): %s", provider.name, error)
            if error.temporary:
                break  # the provider is down: the others wait for the next run
            continue
        checked += 1
        if receipt is not None:
            record(Delivery.objects.filter(pk=pk), receipt, now)
    return checked


# OVHcloud calls this address (set by hand in its manager, see the README).
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
    receipt = callback_receipt(data.get("ptt"), data.get("description", ""))
    if message_id and receipt is not None:
        record(_by_id("ovh", message_id), receipt)
    response = HttpResponse("OK", content_type="text/plain")
    response["X-Robots-Tag"] = "noindex"
    return response


def summary(campaign):
    """SMS receipts of a campaign (message and reminder): count per state."""
    rows = campaign.deliveries.filter(channel=Delivery.Channel.SMS).exclude(receipt="")
    counts = dict.fromkeys(Receipt.values, 0)
    for state in rows.values_list("receipt", flat=True):
        counts[state] += 1
    counts["total"] = sum(counts.values())
    return counts


def to_warn(campaign):
    """People who may not have the message: failed sending, or SMS not received."""
    return (
        campaign.deliveries.filter(
            Q(status=Delivery.Status.FAILED) | Q(receipt__in=[Receipt.UNDELIVERED, Receipt.UNKNOWN])
        )
        .select_related("recipient")
        .order_by("kind", "room_number", "recipient__last_name")
    )


def _by_id(provider_name, message_id):
    return Delivery.objects.filter(
        channel=Delivery.Channel.SMS, sms_provider=provider_name, provider_message_id=message_id
    )
