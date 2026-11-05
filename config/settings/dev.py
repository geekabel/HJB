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
