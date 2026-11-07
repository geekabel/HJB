"""Test helpers: create an account with its roles."""

from accounts.models import User
from accounts.roles import set_roles


def make_user(username, *roles, **fields):
    user = User.objects.create_user(username=username, **fields)
    if roles:
        set_roles(user, roles)
    # Reload from the database: permissions are cached on the object.
    return User.objects.get(pk=user.pk)


def log_in_verified(client, user):
    """Log ``user`` in as after a passkey (verified session, card T14).

    The staff area and the admin site require a session verified by a
    passkey: force_login() alone is no longer enough. We save a fake passkey
    (never used to sign) and store it in the session, as
    django_otp.login() does.
    """
    import os

    from django_otp import DEVICE_ID_SESSION_KEY
    from django_otp_webauthn.utils import get_credential_model

    client.force_login(user)
    passkey = get_credential_model().objects.create(
        user=user,
        credential_id=os.urandom(16),
        public_key=b"fake-key",
        aaguid="00000000-0000-0000-0000-000000000000",
    )
    session = client.session
    session[DEVICE_ID_SESSION_KEY] = passkey.persistent_id
    session.save()
    return passkey


def confirm_now(client):
    """As if the passkey had just been used again (sensitive actions, T14)."""
    import time

    from access.session_policy import CONFIRMED_AT_KEY

    session = client.session
    session[CONFIRMED_AT_KEY] = time.time()
    session.save()
