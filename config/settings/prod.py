"""Production settings.

All sensitive values come from environment variables
(see ``.env.example``). Checklist followed:
https://docs.djangoproject.com/en/6.1/howto/deployment/checklist/
"""

import os

from .base import *  # noqa: F403
from .base import sms_setting


def _list(name):
    """Read an "a,b,c" environment variable and return a list."""
    return [value.strip() for value in os.environ.get(name, "").split(",") if value.strip()]


DEBUG = False

# Required: the application refuses to start without a key.
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
SECRET_KEY_FALLBACKS = _list("DJANGO_SECRET_KEY_FALLBACKS")

ALLOWED_HOSTS = _list("DJANGO_ALLOWED_HOSTS")

# Address of the admin (T14), for example "gestion-7f3k/". It stays
# protected by the passkey; a little-known address only avoids the noise
# of bots. `check --deploy` reports "admin/" (access.W001).
ADMIN_URL = os.environ.get("DJANGO_ADMIN_URL", "").strip("/") + "/"
if ADMIN_URL == "/":
    ADMIN_URL = "admin/"


# Database: PostgreSQL if POSTGRES_DB is set, else SQLite.
# The final choice is made in T38 (deployment).
# https://docs.djangoproject.com/en/6.1/ref/databases/

if os.environ.get("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ["POSTGRES_DB"],
            "USER": os.environ.get("POSTGRES_USER", ""),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "HOST": os.environ.get("POSTGRES_HOST", ""),
            "PORT": os.environ.get("POSTGRES_PORT", ""),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.environ.get("DJANGO_SQLITE_PATH", BASE_DIR / "db.sqlite3"),  # noqa: F405
        }
    }


# E-mail: a real SMTP server in production (MAILERS, new in 6.1).
# https://docs.djangoproject.com/en/6.1/ref/settings/#mailers

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
        "OPTIONS": {
            "host": os.environ.get("DJANGO_EMAIL_HOST", "localhost"),
            "port": int(os.environ.get("DJANGO_EMAIL_PORT", "587")),
            "username": os.environ.get("DJANGO_EMAIL_USER", ""),
            "password": os.environ.get("DJANGO_EMAIL_PASSWORD", ""),
            "use_tls": os.environ.get("DJANGO_EMAIL_USE_TLS", "1") == "1",
            "timeout": 10,
        },
    },
}
DEFAULT_FROM_EMAIL = os.environ.get("DJANGO_DEFAULT_FROM_EMAIL", "webmaster@localhost")
SERVER_EMAIL = DEFAULT_FROM_EMAIL


# SMS: without DJANGO_SMS_PROVIDER, nothing is sent, and nothing is written
# to the logs (the console would put numbers and codes there). See base.py.

SMS = sms_setting("disabled")


# Passkeys (T13): the site domain, for example "residence.example.fr",
# and its https origins. Without them, `check` reports an error (otp_webauthn.E010, E030).
# Warning: changing the domain makes all passkeys unusable.

OTP_WEBAUTHN_RP_ID = os.environ.get("DJANGO_WEBAUTHN_RP_ID", "")
OTP_WEBAUTHN_ALLOWED_ORIGINS = _list("DJANGO_WEBAUTHN_ORIGINS")
# The admin does not show the public keys.
OTP_ADMIN_HIDE_SENSITIVE_DATA = True

# Wifi passwords (T15): Fernet keys, separated by commas, the newest first.
# Without them, `check` reports an error (housing.E001). Losing them makes the
# stored wifi passwords unreadable: keep a copy outside the server.
WIFI_ENCRYPTION_KEYS = _list("DJANGO_WIFI_KEYS")


# HTTPS
# https://docs.djangoproject.com/en/6.1/topics/security/#ssl-https

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# HSTS: we start with a short duration, then raise it once
# HTTPS is checked (card T37).
SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_SECURE_HSTS_SECONDS", "3600"))

# These two settings affect all subdomains of the chosen domain.
# They stay off until the domain is known (T37):
# so `check --deploy` shows security.W005 and security.W021.
SECURE_HSTS_INCLUDE_SUBDOMAINS = os.environ.get("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS") == "1"
SECURE_HSTS_PRELOAD = os.environ.get("DJANGO_SECURE_HSTS_PRELOAD") == "1"

# Turn on only behind a proxy that overwrites this header.
if os.environ.get("DJANGO_BEHIND_PROXY") == "1":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
