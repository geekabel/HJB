"""Messages d'erreur des clés d'accès, en français.

La bibliothèque renvoie ``{"detail": ..., "code": ...}`` avec un texte anglais
(elle n'a pas de traduction française). On garde son code et on remplace le
texte, montré tel quel à la personne.
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
}
MESSAGE_PAR_DEFAUT = "La clé d'accès n'a pas pu être vérifiée. Réessayez."


def en_francais(code):
    return MESSAGES.get(code, MESSAGE_PAR_DEFAUT)


def reponse_erreur(code, statut, message=None):
    return JsonResponse({"detail": message or en_francais(code), "code": code}, status=statut)


class ErreursEnFrancais:
    """À placer avant une vue de la bibliothèque (BaseWebAuthnView)."""

    def handle_exception(self, exc):
        from django_otp_webauthn.exceptions import OTPWebAuthnApiError

        if isinstance(exc, OTPWebAuthnApiError):
            return reponse_erreur(exc.code, exc.status_code)
        return super().handle_exception(exc)
