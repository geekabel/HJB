"""Login without a passkey, in development only.

Creating a passkey on a development computer is long for a first try. In
development (DEBUG), the command

    python manage.py dev_login marie

prints a link, valid 10 minutes and once, that logs in as that account with a
session that counts as verified (the staff area opens) and as recently
confirmed (sensitive pages open for 10 minutes).

Never in production: the command refuses and the address answers 404 when
DEBUG is off (both tested). The production login stays the passkey.
Django docs: https://docs.djangoproject.com/en/6.1/topics/signing/
"""

import os
import secrets

from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.core import signing
from django.core.cache import cache
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp_webauthn.utils import get_credential_model

from .session_policy import open_session

SALT = "access.dev_login"
LIFETIME = 10 * 60  # seconds
DEVICE_NAME = "Connexion de développement (sans clé)"


def enabled():
    return bool(settings.DEBUG)


def make_link(user, base="http://localhost:8000"):
    if not enabled():
        raise RuntimeError("dev_login only works with DEBUG on.")
    token = signing.dumps({"user": user.pk, "nonce": secrets.token_urlsafe(8)}, salt=SALT)
    return base.rstrip("/") + reverse("dev_login", args=[token])


def _device(user):
    """A stand-in passkey: never used to sign, only to mark the session verified."""
    model = get_credential_model()
    device = model.objects.filter(user=user, name=DEVICE_NAME).first()
    if device is None:
        device = model.objects.create(
            user=user,
            name=DEVICE_NAME,
            credential_id=os.urandom(16),
            public_key=b"development-only",
            aaguid="00000000-0000-0000-0000-000000000000",
        )
    return device


def view(request, token):
    if not enabled():
        raise Http404
    try:
        data = signing.loads(token, salt=SALT, max_age=LIFETIME)
    except signing.BadSignature:
        raise Http404 from None
    if not cache.add(f"dev-login:{data['nonce']}", True, LIFETIME):
        raise Http404  # already used once
    user = get_user_model().objects.filter(pk=data["user"], is_active=True).first()
    if user is None:
        raise Http404
    login(request, user, backend=settings.AUTHENTICATION_BACKENDS[0])
    request.session[DEVICE_ID_SESSION_KEY] = _device(user).persistent_id
    open_session(request, user)
    return redirect("home")
