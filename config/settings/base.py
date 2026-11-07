"""Settings shared by all environments.

The ``dev.py`` and ``prod.py`` files import this module, then add
their own values. The active module is chosen by the
``DJANGO_SETTINGS_MODULE`` environment variable.

Documentation:
https://docs.djangoproject.com/en/6.1/topics/settings/
https://docs.djangoproject.com/en/6.1/ref/settings/
"""

import os
from pathlib import Path

from django.contrib.messages import constants as message_levels
from django.core.exceptions import ImproperlyConfigured
from django.utils.csp import CSP

# Repository root: config/settings/base.py -> three levels up.
BASE_DIR = Path(__file__).resolve().parent.parent.parent


# Applications

INSTALLED_APPS = [
    # Admin site for staff verified by passkey only (T14).
    "config.apps.HJBAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Project apps
    "accounts",
    "ui",
    "audit",
    "housing",
    "residents",
    "sms",
    "activation",
    "access",
    "push",
    "messaging",
    # Anonymous polls (card T25).
    "polls",
    # Appointments with an educator (cards T26 to T29).
    "appointments",
    # Reports of a problem in a room (cards T30 to T33).
    "reports",
    # Staff dashboard (card T35).
    "dashboard",
    # Personal data: information page, retention and purge (card T36).
    "privacy",
    # Backups of the database and the photos, read back (card T37).
    "backups",
    # Settings of the residence, changed by the administration (card T37b).
    "residence",
    # Queue of background tasks in the database, and its worker (card T21).
    "django_tasks_db",
    # Passkeys (card T13): django-otp and its WebAuthn extension.
    # https://django-otp-webauthn.readthedocs.io/en/stable/getting_started/quickstart.html
    "django_otp",
    "django_otp_webauthn",
    # Codes of an authenticator app, for staff only (card T14c).
    # https://django-otp-official.readthedocs.io/en/stable/overview.html#totp-devices
    "django_otp.plugins.otp_totp",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Right after: their headers go on every response, also the refusals of
    # the middlewares below (403 of the staff area). Card T37: Content
    # Security Policy, no framing, browser features the site never uses,
    # and no copy of a personal page in the browser cache.
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "ui.middleware.PermissionsPolicyMiddleware",
    "ui.middleware.PrivatePagesMiddleware",
    # Django's SessionMiddleware, except for the public files of the app (T18).
    "ui.middleware.PublicFilesSessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # After AuthenticationMiddleware (django-otp docs): request.user.is_verified().
    "django_otp.middleware.OTPMiddleware",
    # Staff area and admin: staff with a passkey (T14).
    "access.middleware.StaffAreaMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

# Content Security Policy (card T37), in development too: a violation shows
# at once in the browser console. Only the site's own files: no inline
# script or style, no other origin. Photo previews use blob: images (app.js),
# the service worker and the manifest come from the site.
# https://docs.djangoproject.com/en/6.1/howto/csp/
SECURE_CSP = {
    "default-src": [CSP.NONE],
    "script-src": [CSP.SELF],
    "style-src": [CSP.SELF],
    "img-src": [CSP.SELF, "blob:"],
    "font-src": [CSP.SELF],
    "connect-src": [CSP.SELF],
    "manifest-src": [CSP.SELF],
    "worker-src": [CSP.SELF],
    "form-action": [CSP.SELF],
    "frame-ancestors": [CSP.NONE],
    "base-uri": [CSP.NONE],
    "object-src": [CSP.NONE],
}

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                # Public VAPID key for the once-per-session check of app.js (T19).
                "push.context_processors.push",
                # Unread messages, on the Messages entry of the resident bar (T23).
                "messaging.context_processors.unread",
                # Unread direct messages, on the Rendez-vous entries (T28).
                "appointments.context_processors.unread",
                # New reports, on the Signalements entry of the staff menu (T31).
                "reports.context_processors.new_reports",
            ],
        },
    },
]

# Forms: field template of the design system (ui/forms.py).
FORM_RENDERER = "ui.forms.HJBFormRenderer"

WSGI_APPLICATION = "config.wsgi.application"


# Users
# Custom model, defined before the first migration:
# https://docs.djangoproject.com/en/6.1/topics/auth/customizing/#using-a-custom-user-model-when-starting-a-project

# No password, for residents as well as for staff: login by passkey
# (cards T13 and T14), or, for staff only, by the code of an authenticator
# app (card T14c, access/app_code.py).
LOGIN_URL = "access:login"
LOGIN_REDIRECT_URL = "home"
AUTHENTICATION_BACKENDS = [
    "django_otp_webauthn.backends.WebAuthnBackend",
    # Role permissions only: this backend refuses any password.
    "accounts.backends.PermissionsOnlyBackend",
]

# Address of the Django admin. In production, it comes from
# DJANGO_ADMIN_URL (see prod.py): we avoid "admin/", the most targeted address.
ADMIN_URL = "admin/"

# Length of a session without activity. Residents logged in by passkey
# keep theirs much longer (see access/session_policy.py).
SESSION_COOKIE_AGE = 12 * 60 * 60
# The timer restarts on each request: it really is a length "without activity".
SESSION_SAVE_EVERY_REQUEST = True

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Language and time zone
# https://docs.djangoproject.com/en/6.1/topics/i18n/

LANGUAGE_CODE = "fr-fr"

TIME_ZONE = "Europe/Paris"

USE_I18N = True

USE_TZ = True


# Static files
# https://docs.djangoproject.com/en/6.1/howto/static-files/

STATIC_URL = "static/"
# Where collectstatic copies the files; Caddy serves them (deploy/).
STATIC_ROOT = Path(os.environ.get("DJANGO_STATIC_ROOT") or BASE_DIR / "staticfiles")


# Messages: the levels take the names of the design system banners
# (classes alert--success, alert--info, alert--warning).
# https://docs.djangoproject.com/en/6.1/ref/contrib/messages/#message-tags

MESSAGE_TAGS = {
    message_levels.DEBUG: "info",
    message_levels.INFO: "info",
    message_levels.SUCCESS: "success",
    message_levels.WARNING: "warning",
    message_levels.ERROR: "warning",
}


# E-mail: shown in the console until the provider is chosen.
# https://docs.djangoproject.com/en/6.1/topics/email/#topic-email-configuration

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.console.EmailBackend",
    },
}


# SMS: swappable provider (sms app, card T10).
# DJANGO_SMS_PROVIDER: console (nothing is sent), smsgate, ovh or disabled.
# Credentials always come from the environment (see .env.example).

SMS_PROVIDERS = {
    "disabled": ("sms.providers.disabled.DisabledProvider", {}),
    "console": ("sms.providers.console.ConsoleProvider", {}),
    "smsgate": (
        "sms.providers.smsgate.SmsGateProvider",
        {
            "url": "SMSGATE_URL",
            "token": "SMSGATE_TOKEN",
            "username": "SMSGATE_USERNAME",
            "password": "SMSGATE_PASSWORD",
            "sim": "SMSGATE_SIM",
        },
    ),
    "ovh": (
        "sms.providers.ovh.OvhProvider",
        {
            "endpoint": "OVH_ENDPOINT",
            "service": "OVH_SMS_SERVICE",
            "application_key": "OVH_APPLICATION_KEY",
            "application_secret": "OVH_APPLICATION_SECRET",
            "consumer_key": "OVH_CONSUMER_KEY",
            "sender": "OVH_SMS_SENDER",
            "user": "OVH_SMS_USER",
        },
    ),
}


def sms_setting(default):
    """SMS setting read from the environment. ``default``: console or disabled."""
    choice = os.environ.get("DJANGO_SMS_PROVIDER") or default
    if choice not in SMS_PROVIDERS:
        raise ImproperlyConfigured(
            f"DJANGO_SMS_PROVIDER={choice!r} : valeurs possibles {', '.join(SMS_PROVIDERS)}."
        )
    backend, variables = SMS_PROVIDERS[choice]
    return {
        "BACKEND": backend,
        "OPTIONS": {key: os.environ.get(variable, "") for key, variable in variables.items()},
    }


# In development, the console shows the SMS. Production refuses to send
# until a provider is chosen (see prod.py).
SMS = sms_setting("console")

# Delivery receipts of OVHcloud (card T24): secret part of the callback address.
# Letters, digits, "-" and "_" only (sms/checks.py).
SMS_RECEIPT_SECRET = os.environ.get("DJANGO_SMS_RECEIPT_SECRET", "")

# Tests: no real SMS, see tools/test_runner.py.
TEST_RUNNER = "tools.test_runner.HJBTestRunner"


# Passkeys, card T13
# https://django-otp-webauthn.readthedocs.io/en/stable/getting_started/quickstart.html
# The domain (RP ID) and the allowed origins depend on the site address:
# they are in dev.py and prod.py. Changing the domain makes the passkeys unusable.

OTP_WEBAUTHN_RP_NAME = "Habitat Jeunes Belfort"
# Name shown in the authenticator app, next to the username (card T14c).
OTP_TOTP_ISSUER = "Habitat Jeunes Belfort"
OTP_WEBAUTHN_HELPER_CLASS = "access.webauthn.HJBWebAuthnHelper"


# Wifi passwords, card T15
# They are encrypted with Fernet (cryptography library); the keys never live
# in the repository. WIFI_ENCRYPTION_KEYS is a list: the first key encrypts,
# all of them decrypt (key rotation, see housing/wifi_crypto.py).
# https://cryptography.io/en/latest/fernet/

WIFI_ENCRYPTION_KEYS = []


# Web Push notifications, card T19
# The server signs each message with its VAPID key (push/vapid.py). The private
# key never lives in the repository. The contact (mailto: or https://) lets a
# push service reach the owner of the server in case of problem.

VAPID_PRIVATE_KEY = ""
VAPID_CONTACT = ""


# Background tasks, card T21 (https://docs.djangoproject.com/en/6.1/topics/tasks/)
# Development and tests: tasks run at once, in the request. Production
# (prod.py): django-tasks-db keeps them in the database, and its worker
# ("manage.py db_worker") runs them.

TASKS = {"default": {"BACKEND": "django.tasks.backends.immediate.ImmediateBackend"}}


# Address of the site, for the links written outside a request: the personal
# reply link of an SMS (card T22), sent by the task worker.

SITE_URL = ""


# Reports, card T30
# The photos stay private: they live outside the static files, and only a view
# that checks who asks serves them (reports/resident_views.py). No MEDIA_URL.
# https://docs.djangoproject.com/en/6.1/topics/files/

MEDIA_ROOT = Path(os.environ.get("DJANGO_MEDIA_ROOT") or BASE_DIR / "media")

# The number to call at once for a serious problem is a residence setting
# (residence app, card T37b), changed by the administration.

# At most 10 files in one request (3 photos per report). The total size of a
# request is limited by the web server in front of Django (card T38, nginx
# client_max_body_size): Django does not count the files in it.
# https://docs.djangoproject.com/en/6.1/ref/settings/#data-upload-max-number-files
DATA_UPLOAD_MAX_NUMBER_FILES = 10


# Personal data, card T36: the retention durations and the contact are
# residence settings (residence app, card T37b), changed by the
# administration on the page "Réglages".


# PostgreSQL, from the environment: production (card T38), and development
# or tests when POSTGRES_DB is set (the CI runs the tests on it too).
def postgres_setting():
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["POSTGRES_DB"],
        "USER": os.environ.get("POSTGRES_USER", ""),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", ""),
        "PORT": os.environ.get("POSTGRES_PORT", ""),
        # Keep a connection a minute, and check it before use.
        # https://docs.djangoproject.com/en/6.1/ref/databases/#persistent-connections
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
    }


# Addresses of a reverse proxy whose X-Forwarded-For is believed (card T38).
# None in development: REMOTE_ADDR is the client.
TRUSTED_PROXIES = []
