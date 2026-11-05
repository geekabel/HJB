"""Réglages des cérémonies WebAuthn (bibliothèque django-otp-webauthn).

La classe « helper » est le point prévu pour adapter la bibliothèque :
https://django-otp-webauthn.readthedocs.io/en/stable/how_to_guides/customize_helper_class.html
Toute la cryptographie reste dans py_webauthn, appelée par la bibliothèque.
"""

from django_otp_webauthn.helpers import WebAuthnHelper


class AideWebAuthn(WebAuthnHelper):
    def get_credential_display_name(self, user):
        # Montré par le téléphone dans sa liste de clés : le nom, pas l'identifiant technique.
        return user.get_full_name() or user.get_username()


class AideActivation(AideWebAuthn):
    """Pour l'activation : la nouvelle clé remplace les anciennes.

    Les clés existantes ne sont donc pas envoyées au navigateur
    (``excludeCredentials``). Sinon, un téléphone qui a déjà une clé pour ce
    compte refuserait d'en créer une nouvelle.
    """

    def get_generate_registration_options_kwargs(self, *, user):
        options = super().get_generate_registration_options_kwargs(user=user)
        options["exclude_credentials"] = []
        return options
