"""Passkey error messages, in French.

The library returns ``{"detail": ..., "code": ...}`` with an English text
(it has no French translation). We keep its code and replace the text,
which is shown as is to the person.
"""

from django.http import JsonResponse

MESSAGES = {
    "malformed_request": "La demande est illisible. Rechargez la page, puis réessayez.",
    "invalid_state": "La vérification a expiré. Réessayez.",
    "user_disabled": "Ce compte est désactivé. Passez à l'accueil.",
    "credential_disabled": "Cette clé d'accès est désactivée. Passez à l'accueil.",
    "credential_not_found": (
        "Cette clé d'accès n'est plus valable : elle a sans doute été remplacée. "
        "Passez à l'accueil pour en créer une nouvelle."
    ),
    "credential_user_mismatch": (
        "Cette clé d'accès appartient à un autre compte. Déconnectez-vous d'abord."
    ),
    "not_authenticated": "Connectez-vous d'abord.",
    "user_not_verified": "Confirmez d'abord votre identité avec votre clé d'accès.",
    "credential_exists": "Cette clé d'accès est déjà enregistrée. Essayez de vous connecter.",
}
DEFAULT_MESSAGE = "La clé d'accès n'a pas pu être vérifiée. Réessayez."


def message_for(code):
    return MESSAGES.get(code, DEFAULT_MESSAGE)


def error_response(code, status, message=None):
    return JsonResponse({"detail": message or message_for(code), "code": code}, status=status)


class FrenchErrorsMixin:
    """Put it before a library view (BaseWebAuthnView)."""

    def handle_exception(self, exc):
        from django_otp_webauthn.exceptions import OTPWebAuthnApiError

        if isinstance(exc, OTPWebAuthnApiError):
            return error_response(exc.code, exc.status_code)
        return super().handle_exception(exc)
