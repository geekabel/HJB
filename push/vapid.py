"""VAPID key of the server (card T19).

The push services (Google, Mozilla, Apple, Microsoft) accept a message only
if it is signed with the key whose public part the browser received at
subscription. The private key lives in DJANGO_VAPID_PRIVATE_KEY, never in the
repository: 32 bytes in base64url (raw P-256 key, as py_vapid reads it).
Create one with: python manage.py vapid_key
Docs: https://github.com/web-push-libs/vapid/tree/main/python
"""

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from py_vapid import Vapid02


def _b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def new_private_key():
    """A new raw private key, in base64url (for the .env file)."""
    key = ec.generate_private_key(ec.SECP256R1())
    return _b64url(key.private_numbers().private_value.to_bytes(32, "big"))


def vapid():
    """The Vapid02 object of the server. Raises ImproperlyConfigured if the key is missing."""
    raw = settings.VAPID_PRIVATE_KEY
    if not raw:
        raise ImproperlyConfigured("VAPID_PRIVATE_KEY is empty (DJANGO_VAPID_PRIVATE_KEY).")
    try:
        return Vapid02.from_raw(raw.encode())
    except Exception as error:  # wrong length, not base64url, not on the curve
        raise ImproperlyConfigured("VAPID_PRIVATE_KEY is not a valid P-256 key.") from error


def application_server_key():
    """The public key given to the browser (applicationServerKey), in base64url."""
    point = vapid().public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return _b64url(point)
