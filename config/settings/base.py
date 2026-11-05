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
    # Queue of background tasks in the database, and its worker (card T21).
    "django_tasks_db",
    # Passkeys (card T13): django-otp and its WebAuthn extension.
    # https://django-otp-webauthn.readthedocs.io/en/stable/getting_started/quickstart.html
    "django_otp",
    "django_otp_webauthn",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
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
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

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

# Login by passkey only (cards T13 and T14): no password,
# for residents as well as for staff.
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
STATIC_ROOT = BASE_DIR / "staticfiles"


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

# Tests: no real SMS, see tools/test_runner.py.
TEST_RUNNER = "tools.test_runner.HJBTestRunner"


# Passkeys, card T13
# https://django-otp-webauthn.readthedocs.io/en/stable/getting_started/quickstart.html
# The domain (RP ID) and the allowed origins depend on the site address:
# they are in dev.py and prod.py. Changing the domain makes the passkeys unusable.

OTP_WEBAUTHN_RP_NAME = "Habitat Jeunes Belfort"
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
