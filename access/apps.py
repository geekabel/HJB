from django.apps import AppConfig


class AccessConfig(AppConfig):
    name = "access"
    verbose_name = "Connexion"

    def ready(self):
        # When a resident leaves (T09), their passkeys are deleted.
        from django.db.models.signals import post_delete
        from django_otp.plugins.otp_totp.models import TOTPDevice
        from django_otp_webauthn.utils import get_credential_model

        from residents.departure import departure_recorded

        from . import checks  # noqa: F401 (registers the checks)
        from .admin import register_app_code_admin
        from .signals import close_sessions_after_delete, remove_passkeys_on_departure

        departure_recorded.connect(
            remove_passkeys_on_departure, dispatch_uid="access.remove_passkeys"
        )
        # A deleted passkey or app code closes the sessions of its account.
        post_delete.connect(
            close_sessions_after_delete,
            sender=get_credential_model(),
            dispatch_uid="access.close_sessions",
        )
        post_delete.connect(
            close_sessions_after_delete,
            sender=TOTPDevice,
            dispatch_uid="access.close_sessions_app_code",
        )
        register_app_code_admin()
