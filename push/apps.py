from django.apps import AppConfig


class PushConfig(AppConfig):
    name = "push"
    verbose_name = "Notifications"

    def ready(self):
        from django.contrib.auth.signals import user_logged_out
        from django.db.models.signals import post_delete
        from django_otp.plugins.otp_totp.models import TOTPDevice
        from django_otp_webauthn.utils import get_credential_model

        from . import checks  # noqa: F401 (registers the checks)
        from .signals import forget_device_on_logout, forget_devices_after_passkey_delete

        # A deleted passkey (lost phone, departure, new activation): the
        # devices of the account stop receiving notifications.
        post_delete.connect(
            forget_devices_after_passkey_delete,
            sender=get_credential_model(),
            dispatch_uid="push.forget_devices",
        )
        post_delete.connect(
            forget_devices_after_passkey_delete,
            sender=TOTPDevice,
            dispatch_uid="push.forget_devices_app_code",
        )
        # Logout: this device stops receiving the notifications of the account.
        user_logged_out.connect(forget_device_on_logout, dispatch_uid="push.forget_device")
