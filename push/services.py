"""Send notifications to the devices of a person (card T19).

Docs:
- pywebpush: https://github.com/web-push-libs/pywebpush
- Push API: https://developer.mozilla.org/en-US/docs/Web/API/Push_API

The service worker (ui/templates/ui/sw.js) shows the message. A device that
the push service no longer knows (404 or 410) is deleted at once; one that
fails MAX_FAILURES times in a row too.
"""

import json
import logging
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from pywebpush import WebPushException, webpush

from .models import PushSubscription
from .vapid import vapid

logger = logging.getLogger(__name__)

MAX_FAILURES = 5
MAX_DEVICES = 10  # per person: the oldest is removed beyond that
TIMEOUT = 10  # seconds, per device
TTL = 24 * 60 * 60  # the push service keeps a message one day for an offline device
TITLE_LENGTH = 80
BODY_LENGTH = 300

# The browser gives the address of its push service; the server then sends to
# it. Only the known services are accepted, so that the server never sends a
# request to any other address (SSRF). Host, or end of the host after a dot.
PUSH_SERVICE_HOSTS = (
    "fcm.googleapis.com",  # Chrome, Edge on Android, Samsung Internet, Opera
    "updates.push.services.mozilla.com",  # Firefox
    "push.apple.com",  # Safari: web.push.apple.com
    "notify.windows.com",  # Edge on Windows: *.notify.windows.com
)


def endpoint_allowed(endpoint):
    try:
        parts = urlsplit(endpoint)
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or parts.port not in (None, 443) or parts.username:
        return False
    return any(host == known or host.endswith("." + known) for known in PUSH_SERVICE_HOSTS)


def device_label(user_agent):
    """A short French label of the device, from its User-Agent ("Chrome sur Android")."""
    agent = user_agent or ""
    if "iPhone" in agent or "iPad" in agent:
        system = "iPhone" if "iPhone" in agent else "iPad"
    elif "Android" in agent:
        system = "Android"
    elif "Windows" in agent:
        system = "Windows"
    elif "Mac OS X" in agent or "Macintosh" in agent:
        system = "Mac"
    elif "Linux" in agent:
        system = "Linux"
    else:
        system = ""
    if "Edg/" in agent or "EdgA/" in agent:
        browser = "Edge"
    elif "SamsungBrowser" in agent:
        browser = "Samsung Internet"
    elif "Firefox/" in agent or "FxiOS" in agent:
        browser = "Firefox"
    elif "Chrome/" in agent or "CriOS" in agent:
        browser = "Chrome"
    elif "Safari/" in agent:
        browser = "Safari"
    else:
        browser = "Navigateur"
    return f"{browser} sur {system}" if system else browser


@transaction.atomic
def save_subscription(user, *, endpoint, p256dh, auth, user_agent=""):
    """Record (or move to this person) the device. Return the subscription.

    The same browser used by someone else before (shared phone) now belongs
    to this person only.
    """
    subscription, _ = PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            "user": user,
            "p256dh": p256dh,
            "auth": auth,
            "device": device_label(user_agent)[:100],
            "failures": 0,
        },
    )
    extra = PushSubscription.objects.filter(user=user).order_by("-created_at")[MAX_DEVICES:]
    PushSubscription.objects.filter(pk__in=[s.pk for s in extra]).delete()
    return subscription


@dataclass
class SendResult:
    sent: int = 0
    failed: int = 0
    removed: int = 0


def _payload(title, body, url, tag):
    if not url.startswith("/") or url.startswith("//"):
        raise ValueError("url must be a path of this site")
    data = {"title": title[:TITLE_LENGTH], "body": body[:BODY_LENGTH], "url": url}
    if tag:
        data["tag"] = tag
    return json.dumps(data, ensure_ascii=False)


def send_to_user(user, *, title, body, url="/", tag="", urgency="normal"):
    """Send one notification to each device of the person. Return a SendResult.

    ``url``: the page opened by a tap on the notification (a path of this site).
    ``tag``: a new message with the same tag replaces the previous one on the device.
    ``urgency``: "very-low", "low", "normal" or "high" (RFC 8030).
    """
    payload = _payload(title, body, url, tag)
    key = vapid()
    result = SendResult()
    for subscription in PushSubscription.objects.filter(user=user):
        outcome = _send_one(subscription, payload, key, urgency)
        setattr(result, outcome, getattr(result, outcome) + 1)
    return result


def _send_one(subscription, payload, key, urgency):
    host = urlsplit(subscription.endpoint).hostname
    if not endpoint_allowed(subscription.endpoint):
        subscription.delete()
        return "removed"
    try:
        webpush(
            subscription.as_subscription_info(),
            payload,
            vapid_private_key=key,
            vapid_claims={"sub": settings.VAPID_CONTACT},  # a new dict: webpush() fills it in
            ttl=TTL,
            headers={"Urgency": urgency},
            timeout=TIMEOUT,
        )
    except WebPushException as error:
        status = error.response.status_code if error.response is not None else None
        if status in (404, 410):
            # The browser unsubscribed, or the subscription expired.
            subscription.delete()
            return "removed"
        logger.warning("Push to %s failed with status %s", host, status)
        return _count_failure(subscription)
    except requests.RequestException as error:
        logger.warning("Push to %s failed: %s", host, type(error).__name__)
        return _count_failure(subscription)
    subscription.last_success_at = timezone.now()
    subscription.failures = 0
    subscription.save(update_fields=["last_success_at", "failures"])
    return "sent"


def _count_failure(subscription):
    subscription.failures += 1
    if subscription.failures >= MAX_FAILURES:
        subscription.delete()
        return "removed"
    subscription.save(update_fields=["failures"])
    return "failed"


def prune():
    """Delete the devices of disabled accounts and those that fail too often."""
    deleted, _ = PushSubscription.objects.filter(user__is_active=False).delete()
    more, _ = PushSubscription.objects.filter(failures__gte=MAX_FAILURES).delete()
    return deleted + more
