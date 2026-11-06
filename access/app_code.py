"""Login with the code of an authenticator app, for staff only (card T14c).

A passkey on a computer can be hard to set up. Staff can instead use an
authenticator app on their phone (Google Authenticator, Microsoft
Authenticator, FreeOTP...): it shows a new 6-digit code every 30 seconds
(TOTP, RFC 6238). Residents keep the passkey, simpler on a phone.

django-otp does the hard part: each code works once (replay protection),
and wrong codes slow the next tries down (throttling).
Docs: https://django-otp-official.readthedocs.io/en/stable/overview.html#totp-devices
"""

import base64

import segno
from django_otp.plugins.otp_totp.models import TOTPDevice

from .session_policy import is_resident

DEVICE_NAME = "Application de codes"


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


def verify(device, value):
    """True if the code is right. A wrong code counts toward the throttling."""
    token = clean_token(value)
    if not token:
        return False
    return device.verify_token(token)


def device_of(user):
    """The confirmed app code of ``user``, or None."""
    return TOTPDevice.objects.filter(user=user, confirmed=True).first()
