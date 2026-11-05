"""Answer "Présent" or "Absent" (card T22).

Each recipient gets a personal link, in the SMS and behind the buttons of the
notification. The link is signed (HMAC of the secret key, as in
https://docs.djangoproject.com/en/6.1/topics/signing/) and short: Django's full
signature would add about 60 characters to every SMS. It names the message and
the person; nobody can make a link for another person without the secret key.

    /r/<message>-<person>-<signature>     for example /r/2s-k1-Vh3sQ0b1cD9_
"""

import base64
from datetime import datetime, time, timedelta

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from .models import AttendanceReply, Campaign, ReplyType

SALT = "messaging.replies.link"
# Previews and test sends (composer, "M'envoyer un test"): a link of the same
# length that never works, so the staff never see a resident's real link.
PREVIEW_SALT = "messaging.replies.preview"
SIGNATURE_BYTES = 9  # 72 bits, 12 characters
OPEN_WITHOUT_DATE = timedelta(days=7)
DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"


def _base36(number):
    text = ""
    while True:
        number, rest = divmod(number, 36)
        text = DIGITS[rest] + text
        if not number:
            return text


def _signature(campaign_id, user_id, secret=None, salt=SALT):
    mac = salted_hmac(salt, f"{campaign_id}:{user_id}", secret=secret, algorithm="sha256").digest()
    return base64.urlsafe_b64encode(mac[:SIGNATURE_BYTES]).decode()


def make_token(campaign_id, user_id, salt=SALT):
    signature = _signature(campaign_id, user_id, salt=salt)
    return f"{_base36(campaign_id)}-{_base36(user_id)}-{signature}"


def read_token(token):
    """(campaign_id, user_id) if the link is genuine, otherwise None."""
    parts = (token or "").split("-", 2)
    if len(parts) != 3 or len(token) > 60:
        return None
    try:
        campaign_id, user_id = int(parts[0], 36), int(parts[1], 36)
    except ValueError:
        return None
    # The old keys still open the links sent before a key change, as Django's
    # Signer does (https://docs.djangoproject.com/en/6.1/ref/settings/#secret-key-fallbacks).
    for secret in (settings.SECRET_KEY, *settings.SECRET_KEY_FALLBACKS):
        if constant_time_compare(parts[2], _signature(campaign_id, user_id, secret)):
            return campaign_id, user_id
    return None


def reply_path(campaign_id, user_id):
    return reverse("reply", args=[make_token(campaign_id, user_id)])


def reply_url(campaign_id, user_id, live=True):
    """``live=False``: a preview link, of the same length, that never works."""
    token = make_token(campaign_id, user_id, salt=SALT if live else PREVIEW_SALT)
    return settings.SITE_URL.rstrip("/") + reverse("reply", args=[token])


def sms_suffix(campaign_id, user_id, live=True):
    """Added to the SMS of a message that asks for an answer."""
    return f" Présent ou absent ? Répondez : {reply_url(campaign_id, user_id, live)}"


def vote_sms_suffix(campaign_id, user_id, live=True):
    """Added to the SMS of a vote (card T25): the same personal link."""
    return f" Votez ici : {reply_url(campaign_id, user_id, live)}"


def closes_at(campaign):
    """Answers are taken until the evening of the event (or 7 days without a date)."""
    if campaign.event_date:
        return timezone.make_aware(
            datetime.combine(campaign.event_date + timedelta(days=1), time(0, 0))
        )
    start = campaign.started_at or campaign.send_at or timezone.now()
    return start + OPEN_WITHOUT_DATE


def is_open(campaign, now=None):
    return (
        campaign.reply_type == ReplyType.ATTENDANCE
        and campaign.status in (Campaign.Status.SENDING, Campaign.Status.SENT)
        and (now or timezone.now()) < closes_at(campaign)
    )


def record(campaign, resident, answer):
    """Save (or change) the answer. Return the AttendanceReply."""
    if answer not in AttendanceReply.Answer.values:
        raise ValueError("unknown answer")
    with transaction.atomic():
        reply, _ = AttendanceReply.objects.update_or_create(
            campaign=campaign, resident=resident, defaults={"answer": answer}
        )
    return reply


def counts(campaign):
    """Answers to the message: present, absent, no answer.

    Every answer counts, even from a person whose SMS is marked uncertain (the
    link proves it arrived). "No answer" only counts the messages surely sent.
    """
    from .models import Delivery

    reached = set(
        campaign.deliveries.filter(
            kind=Delivery.Kind.MESSAGE, status=Delivery.Status.SENT
        ).values_list("recipient_id", flat=True)
    )
    answers = dict(campaign.replies.values_list("resident_id", "answer"))
    present = sum(1 for answer in answers.values() if answer == "present")
    absent = sum(1 for answer in answers.values() if answer == "absent")
    return {
        "present": present,
        "absent": absent,
        "none": len(reached - set(answers)),
        "answers": answers,
    }
