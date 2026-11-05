from django.apps import AppConfig


class AccessConfig(AppConfig):
    name = "access"
    verbose_name = "Connexion"

    def ready(self):
        # When a resident leaves (T09), their passkeys are deleted.
        from django.db.models.signals import post_delete
        from django_otp_webauthn.utils import get_credential_model

        from residents.departure import departure_recorded

        from . import checks  # noqa: F401 (registers the checks)
        from .signals import close_sessions_after_delete, remove_passkeys_on_departure

        departure_recorded.connect(
            remove_passkeys_on_departure, dispatch_uid="access.remove_passkeys"
        )
        # A deleted passkey closes the sessions of its account.
        post_delete.connect(
            close_sessions_after_delete,
            sender=get_credential_model(),
            dispatch_uid="access.close_sessions",
        )
