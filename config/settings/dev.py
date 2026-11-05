"""Development settings, used by default by ``manage.py``.

Never use these settings in production.
https://docs.djangoproject.com/en/6.1/howto/deployment/checklist/
"""

import base64
import hashlib
import os

from .base import *  # noqa: F403

DEBUG = True

# Development key only. Production reads its own key
# from the environment (see prod.py).
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-cle-de-developpement-a-ne-jamais-utiliser-en-production",  # gitleaks:allow
)

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",  # noqa: F405
    }
}

# Passkeys: WebAuthn refuses IP addresses. Open http://localhost:8000,
# not http://127.0.0.1:8000 (django-otp-webauthn docs).
OTP_WEBAUTHN_RP_ID = os.environ.get("DJANGO_WEBAUTHN_RP_ID", "localhost")
OTP_WEBAUTHN_ALLOWED_ORIGINS = os.environ.get(
    "DJANGO_WEBAUTHN_ORIGINS", "http://localhost:8000"
).split(",")

# Wifi passwords: a development key derived from SECRET_KEY, unless
# DJANGO_WIFI_KEYS is set. Never used in production (see prod.py).
WIFI_ENCRYPTION_KEYS = [
    key.strip() for key in os.environ.get("DJANGO_WIFI_KEYS", "").split(",") if key.strip()
] or [base64.urlsafe_b64encode(hashlib.sha256(b"hjb.wifi:" + SECRET_KEY.encode()).digest())]


# Web Push (T19): a VAPID key derived from the development secret key, unless
# DJANGO_VAPID_PRIVATE_KEY is set. Never used in production (see prod.py).
# The scalar is reduced into [1, n - 1], so the key is always valid on P-256.
_P256_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_dev_scalar = (
    int.from_bytes(hashlib.sha256(b"hjb.vapid:" + SECRET_KEY.encode()).digest()) % (_P256_ORDER - 1)
    + 1
)
VAPID_PRIVATE_KEY = os.environ.get("DJANGO_VAPID_PRIVATE_KEY") or (
    base64.urlsafe_b64encode(_dev_scalar.to_bytes(32, "big")).rstrip(b"=").decode()
)
VAPID_CONTACT = os.environ.get("DJANGO_VAPID_CONTACT", "mailto:dev@example.org")

SITE_URL = os.environ.get("DJANGO_SITE_URL", "http://localhost:8000")
