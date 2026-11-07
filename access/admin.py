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


class AppCodeAdmin(admin.ModelAdmin):
    """App codes of the staff (card T14c): read, unlock and delete only.

    Never added or changed here: a code is linked only through the
    activation (SMS, then the app), and the key is never shown. Deleting one
    closes the sessions of the account (access/signals.py).
    """

    list_display = ("user", "name", "confirmed", "throttling_failure_count", "last_used_at")
    list_filter = ("confirmed",)
    search_fields = ("user__username", "user__first_name", "user__last_name")
    fields = ("user", "name", "confirmed", "throttling_failure_count", "last_used_at")
    readonly_fields = fields
    actions = ("unlock",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.action(description="Débloquer après des essais faux")
    def unlock(self, request, queryset):
        count = queryset.update(throttling_failure_count=0, throttling_failure_timestamp=None)
        self.message_user(request, f"{count} application(s) débloquée(s).")


def register_app_code_admin():
    """Replace the admin of django-otp (add and change views, key shown in development).

    Called from AccessConfig.ready(): the admin modules are all loaded by then.
    """
    from django_otp.plugins.otp_totp.models import TOTPDevice

    if admin.site.is_registered(TOTPDevice):
        admin.site.unregister(TOTPDevice)
    admin.site.register(TOTPDevice, AppCodeAdmin)
