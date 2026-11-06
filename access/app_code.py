"""Login with the code of an authenticator app, for staff only (card T14c).

A passkey on a computer can be hard to set up. Staff can instead use an
authenticator app on their phone (Google Authenticator, Microsoft
Authenticator, FreeOTP...): it shows a new 6-digit code every 30 seconds
(TOTP, RFC 6238). Residents keep the passkey, simpler on a phone.

django-otp does the hard part: each code works once (replay protection),
and wrong codes slow the next tries down (throttling, 1, 2, 4... seconds).
We add three things (independent review of T14c):
- the check runs under a row lock, so parallel tries cannot skip the
  throttling or use one code twice (``for_verify`` in the django-otp docs);
- the wait stops growing after 10 wrong codes (8.5 minutes): a stranger who
  knows a username cannot lock the person out for days;
- a person who types the right code while the wait runs is told to wait.
Docs: https://django-otp-official.readthedocs.io/en/stable/overview.html#totp-devices
"""

import base64
import os
import time

import segno
from django.db import transaction
from django_otp.oath import TOTP
from django_otp.plugins.otp_totp.models import TOTPDevice

from audit.models import Action
from audit.service import log_action

from .session_policy import is_resident

DEVICE_NAME = "Application de codes"
MAX_FAILURES = 10  # the wait stops growing here: 2 ** 9 seconds, 8.5 minutes
REPORTED_FAILURES = 5  # the audit log notes the account once, at this count


def allowed(user):
    """App codes are for staff accounts only."""
    return user is not None and user.is_active and not is_resident(user)


def new_device(user):
    """A new unconfirmed app code for ``user`` (the other unconfirmed ones go)."""
    TOTPDevice.objects.filter(user=user, confirmed=False).delete()
    return TOTPDevice.objects.create(user=user, name=DEVICE_NAME, confirmed=False)


def qr_svg(device, title):
    """The QR code to scan with the app, as inline SVG (made by segno from our own data)."""
    return segno.make_qr(device.config_url, error="m").svg_inline(scale=4, title=title)


def secret(device):
    """The key in groups of 4 letters, for an app that cannot scan."""
    key = base64.b32encode(device.bin_key).decode().rstrip("=")
    return " ".join(key[i : i + 4] for i in range(0, len(key), 4))


def clean_token(value):
    """The 6 digits, without spaces; empty if it does not look like a code."""
    token = "".join((value or "").split())
    return token if token.isdigit() and len(token) == 6 else ""


def device_of(user):
    """The confirmed app code of ``user``, or None."""
    return TOTPDevice.objects.filter(user=user, confirmed=True).first()


class Waiting(Exception):
    """The code is right, but the account must wait after earlier wrong codes."""

    def __init__(self, seconds):
        super().__init__(seconds)
        self.minutes = max(1, round(seconds / 60))


def _right_now(device, token):
    """Whether ``token`` is the current code, without counting anything."""
    totp = TOTP(device.bin_key, device.step, device.t0, device.digits, device.drift)
    totp.time = time.time()
    return totp.verify(int(token), device.tolerance, device.last_t + 1)


def verify(device, value, request=None):
    """True if the code is right. Raise Waiting if it is right but too early.

    Runs under a lock on the device row: one check at a time per account.
    """
    token = clean_token(value)
    with transaction.atomic():
        device = TOTPDevice.objects.select_for_update().get(pk=device.pk)
        allowed_now, data = device.verify_is_allowed()
        if not allowed_now:
            if token and _right_now(device, token):
                locked_until = data.get("locked_until")
                seconds = (locked_until.timestamp() - time.time()) if locked_until else 60
                raise Waiting(seconds)
            return False
        if token and device.verify_token(token):
            return True
        if not token:
            device.throttle_increment(commit=True)
        if device.throttling_failure_count > MAX_FAILURES:
            TOTPDevice.objects.filter(pk=device.pk).update(throttling_failure_count=MAX_FAILURES)
        elif device.throttling_failure_count == REPORTED_FAILURES:
            log_action(
                Action.APP_CODE_FAILURES,
                target=device.user,
                details={"failures": REPORTED_FAILURES},
                request=request,
            )
        return False


def same_work_without_device():
    """About the work of a real check, when there is no device: the time taken
    does not tell whether the username exists."""
    with transaction.atomic():
        TOTPDevice.objects.select_for_update().filter(pk=0).first()
    TOTP(os.urandom(20)).verify(0, 1, 0)
