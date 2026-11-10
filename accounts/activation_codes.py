"""Activation codes (card T11).

At the front desk, when the person comes in, the staff issues a code. The
person enters it on /activer/, then verifies their phone (T12) and creates
their passkey (T13).

- The code is shown only once. In the database, we keep its HMAC digest
  (key derived from SECRET_KEY): we can find the entered code, but we
  cannot read a code back from the database.
- Single use, valid for 72 h. A new code cancels the previous one.
- Wrong codes are counted per browser (10) and per IP address (50)
  over one hour. Beyond that, input is blocked. With 2^49 possible codes,
  guessing a code stays out of reach even without these limits.

Python docs: hmac, secrets (https://docs.python.org/3/library/secrets.html).
"""

import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from audit.models import Action
from audit.service import log_action

from .models import ActivationCode, ActivationFailure

# No I, L, O, U, 0 or 1: nothing to confuse when reading a printed code.
ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"
LENGTH = 10  # 30^10: about 2^49 possible codes
VALIDITY = timedelta(hours=72)
MAX_FAILURES = 10  # per browser
MAX_FAILURES_PER_ADDRESS = 50  # per IP address (the residence wifi is shared)
FAILURE_WINDOW = timedelta(hours=1)


class ActivationError(Exception):
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


def normalize(entry):
    """Turn "abcde fghjk" or "ABCDE-FGHJK" into "ABCDEFGHJK"."""
    return "".join(c for c in (entry or "").upper() if c.isalnum())


def format_code(code):
    """Turn "ABCDEFGHJK" into "ABCDE-FGHJK", easier to read and to copy."""
    return f"{code[:5]}-{code[5:]}"


def digest(code):
    key = hashlib.sha256(b"hjb.code-activation:" + settings.SECRET_KEY.encode()).digest()
    return hmac.new(key, normalize(code).encode(), hashlib.sha256).hexdigest()


def issue_code(user, *, by=None, request=None, for_staff=False):
    """Create a code for ``user`` and return it in clear, formatted.

    This person's codes that are still valid are cancelled. A staff code
    (T14) only works for a staff account, and the other way round.
    """
    now = timezone.now()
    for _ in range(5):  # a digest collision is very unlikely; we try again
        code = "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))
        try:
            with transaction.atomic():
                # Same lock as the passkey creation (activation/views.py): a code
                # issued during the passkey creation is sure to cancel it.
                type(user).objects.select_for_update().get(pk=user.pk)
                ActivationCode.objects.valid().filter(user=user).update(cancelled_at=now)
                activation_code = ActivationCode.objects.create(
                    user=user,
                    digest=digest(code),
                    created_by=by,
                    expires_at=now + VALIDITY,
                    for_staff=for_staff,
                )
                log_action(
                    Action.ACTIVATION_CODE_ISSUED,
                    actor=by,
                    target=user,
                    details={
                        "expires_at": activation_code.expires_at.isoformat(),
                        "staff": for_staff,
                    },
                    request=request,
                )
        except IntegrityError:
            continue
        return format_code(code)
    raise RuntimeError("Could not generate a unique code.")


def too_many_failures(ip_address, session_failures=0):
    """True if input must be blocked for now.

    Two limits: 10 failures for one browser (typing mistakes), and 50
    for one IP address. Many residents share the address of the residence
    wifi: a low limit per address would let a single person block
    everyone.
    """
    if session_failures >= MAX_FAILURES:
        return True
    since = timezone.now() - FAILURE_WINDOW
    recent = ActivationFailure.objects.filter(ip_address=ip_address, created_at__gte=since)
    return recent.count() >= MAX_FAILURES_PER_ADDRESS


def redeem_code(entry, ip_address=None, session_failures=0):
    """Check the entered code and mark it as used. Return the ActivationCode.

    Raise ActivationError (code "too_many_attempts" or "invalid").
    """
    if too_many_failures(ip_address, session_failures):
        raise ActivationError(
            "Trop d'essais. Réessayez dans une heure, ou passez à l'accueil.", "too_many_attempts"
        )
    code = normalize(entry)
    found = None
    if len(code) == LENGTH:
        found = (
            ActivationCode.objects.valid()
            .filter(digest=digest(code), user__is_active=True)
            .select_related("user")
            .first()
        )
    # Single use, even if two devices send the code at the same moment. The update
    # checks everything again (cancelled, expired, account disabled in the meantime):
    # a code replaced or cancelled during input does not pass.
    if found is None or not ActivationCode.objects.valid().filter(
        pk=found.pk, user__is_active=True
    ).update(used_at=timezone.now()):
        ActivationFailure.objects.create(ip_address=ip_address)
        # Cleanup: failures older than one day are no longer needed.
        ActivationFailure.objects.filter(created_at__lt=timezone.now() - timedelta(days=1)).delete()
        raise ActivationError(
            "Ce code ne marche pas. Vérifiez-le, ou demandez un nouveau code à l'accueil.",
            "invalid",
        )
    return found


def activation_state(user):
    """Latest code and its state, for the profile page ("active", "used", "expired", None)."""
    latest = user.activation_codes.select_related("created_by").first()
    if latest is None:
        return None, None
    if latest.used_at:
        return latest, "used"
    if latest.cancelled_at or latest.expires_at <= timezone.now():
        return latest, "expired"
    return latest, "active"


def send_code_by_sms(user, url, *, by=None, request=None, for_staff=False):
    """Issue a code and send it by SMS. Return True if the SMS was sent.

    ``url``: the absolute address of the activation page. If sending fails
    with no doubt, the code is cancelled: the profile page stays correct.
    """
    from sms.providers.base import SmsError
    from sms.service import send_sms

    if not user.phone:
        return False
    code = issue_code(user, by=by, request=request, for_staff=for_staff)
    text = (
        f"Habitat Jeunes Belfort : activez votre compte sur {url}#{code} "
        f"(code {code}, valable 72 h, une seule fois)."
    )
    try:
        send_sms(user.phone, text, code=True)
    except SmsError as error:
        if not error.uncertain:
            ActivationCode.objects.valid().filter(user=user).update(cancelled_at=timezone.now())
            return False
    return True
