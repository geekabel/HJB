"""Passkeys in the admin site: read and delete only.

Deleting a passkey cuts the access of the device (a lost phone, for example):
the passkey no longer works, and the open sessions of the account are closed
(access/signals.py).
The library provides the admin class but does not register it.
"""

from django.contrib import admin
from django_otp_webauthn.admin import WebAuthnCredentialAdmin
from django_otp_webauthn.utils import get_credential_model


@admin.register(get_credential_model())
class PasskeyAdmin(WebAuthnCredentialAdmin):
    def has_change_permission(self, request, obj=None):
        return False
