"""Phone verification by SMS code (card T12).

After the activation code, the person gets a 6-digit code on the
number given at the front desk. Entering it proves they have this phone.

- Code drawn with ``secrets``, kept only as an HMAC digest.
- Valid for 10 minutes, 5 attempts at most (the counter is updated in the
  database with a condition: two simultaneous requests do not give one more attempt).
- One new send every 60 seconds at most, 3 per hour. Beyond that,
  the person goes to the front desk.
"""

import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import PhoneVerification

DURATION = timedelta(minutes=10)
MAX_ATTEMPTS = 5
RESEND_DELAY = timedelta(seconds=60)
SENDS_PER_HOUR = 3


class VerificationError(Exception):
    def __init__(self, message, code, **details):
        super().__init__(message)
        self.code = code
        self.details = details


def _digest(verification_id, code):
    key = hashlib.sha256(b"hjb.code-sms:" + settings.SECRET_KEY.encode()).digest()
    message = f"{verification_id}:{code}".encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def latest(user):
    return user.phone_verifications.first()


def resend_available_at(user):
    """Time from which a new code can be requested (None: right away)."""
    previous = latest(user)
    if previous is None or previous.created_at + RESEND_DELAY <= timezone.now():
        return None
    return previous.created_at + RESEND_DELAY


def wait_before_resend(user):
    """Seconds to wait before a new code can be requested (0 if possible now)."""
    previous = latest(user)
    if previous is None:
        return 0
    left = (previous.created_at + RESEND_DELAY - timezone.now()).total_seconds()
    return max(0, int(left + 0.999))


def send_code(user):
    """Send a new code by SMS. Return the PhoneVerification.

    Raise VerificationError: "no_number", "too_soon", "too_many_sends", "sms".
    """
    from sms.providers.base import SmsError
    from sms.service import send_sms

    if not user.phone:
        raise VerificationError(
            "Aucun numéro n'est enregistré pour vous. Passez à l'accueil pour le donner.",
            "no_number",
        )
    code = f"{secrets.randbelow(10**6):06d}"
    with transaction.atomic():
        # Lock on the account row: simultaneous requests go through one by one,
        # and the limits (60 s, 3 per hour) hold even with bursts of clicks.
        type(user).objects.select_for_update().get(pk=user.pk)
        wait = wait_before_resend(user)
        if wait:
            raise VerificationError(
                f"Patientez {wait} secondes avant de demander un nouveau code.",
                "too_soon",
                wait=wait,
            )
        now = timezone.now()
        recent = user.phone_verifications.filter(created_at__gte=now - timedelta(hours=1))
        if recent.count() >= SENDS_PER_HOUR:
            raise VerificationError(
                "Trop de codes envoyés. Réessayez dans une heure, ou passez à l'accueil.",
                "too_many_sends",
            )
        # Only one code at a time: the previous ones expire.
        user.phone_verifications.filter(verified_at__isnull=True, expires_at__gt=now).update(
            expires_at=now
        )
        verification = PhoneVerification.objects.create(
            user=user,
            phone=user.phone,
            digest="",
            expires_at=now + DURATION,
        )
        verification.digest = _digest(verification.pk, code)
        verification.save(update_fields=["digest"])

    text = (
        f"Habitat Jeunes Belfort : votre code de vérification est {code}. "
        "Il expire dans 10 minutes. Ne le donnez à personne."
    )
    try:
        send_sms(user.phone, text)
    except SmsError as error:
        if not error.uncertain:
            # The SMS was not sent: this code cannot be used. The send still counts
            # in the hourly limit, so that the SMS credit is not used up.
            PhoneVerification.objects.filter(pk=verification.pk).update(expires_at=now)
            from sms.providers.disabled import SmsPaused

            if isinstance(error, SmsPaused):
                message = "Les SMS sont coupés pour le moment. Passez à l'accueil."
            else:
                message = (
                    "Le SMS n'a pas pu partir. Réessayez dans une minute, ou passez à l'accueil."
                )
            raise VerificationError(message, "sms") from error
    return verification


def check_code(user, entry):
    """Check the entered code. Return the successful PhoneVerification.

    Raise VerificationError: "none", "too_many_attempts", "incorrect".
    """
    code = "".join(c for c in (entry or "") if c.isdigit())
    verification = (
        user.phone_verifications.filter(
            verified_at__isnull=True,
            expires_at__gt=timezone.now(),
            phone=user.phone,  # the number may have changed since the send
        )
        .order_by("-created_at", "-id")
        .first()
    )
    if verification is None:
        raise VerificationError("Ce code a expiré. Demandez-en un nouveau.", "none")
    # One more attempt, only if some are left: true even with two simultaneous requests.
    if not PhoneVerification.objects.filter(pk=verification.pk, attempts__lt=MAX_ATTEMPTS).update(
        attempts=F("attempts") + 1
    ):
        raise VerificationError(
            "Trop d'essais pour ce code. Demandez-en un nouveau.", "too_many_attempts"
        )
    verification.refresh_from_db(fields=["attempts"])
    if len(code) != 6 or not hmac.compare_digest(
        _digest(verification.pk, code), verification.digest
    ):
        remaining = MAX_ATTEMPTS - verification.attempts
        if remaining <= 0:
            raise VerificationError(
                "Code incorrect, et c'était le dernier essai. Demandez un nouveau code.",
                "too_many_attempts",
            )
        raise VerificationError(
            f"Code incorrect. Il vous reste {remaining} essai{'s' if remaining > 1 else ''}.",
            "incorrect",
            remaining=remaining,
        )
    now = timezone.now()
    with transaction.atomic():
        if not PhoneVerification.objects.filter(
            pk=verification.pk, verified_at__isnull=True
        ).update(verified_at=now):
            raise VerificationError("Ce code a déjà servi.", "none")
        # We keep the verified number: if it changes later, it is no longer verified.
        user.verified_phone = verification.phone
        user.phone_verified_at = now
        user.save(update_fields=["verified_phone", "phone_verified_at"])
    return verification
