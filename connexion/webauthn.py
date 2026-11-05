"""Réglages des cérémonies WebAuthn (bibliothèque django-otp-webauthn).

La classe « helper » est le point prévu pour adapter la bibliothèque :
https://django-otp-webauthn.readthedocs.io/en/stable/how_to_guides/customize_helper_class.html
Toute la cryptographie reste dans py_webauthn, appelée par la bibliothèque.
"""

from django_otp_webauthn.helpers import WebAuthnHelper
from webauthn.helpers.structs import UserVerificationRequirement


class AideWebAuthn(WebAuthnHelper):
    def get_generate_registration_options_kwargs(self, *, user):
        options = super().get_generate_registration_options_kwargs(user=user)
        # La connexion exige Face ID, l'empreinte ou le code de l'appareil. La
        # création l'exige aussi : sinon une clé sans vérification serait
        # enregistrée (et remplacerait les autres) sans jamais pouvoir servir.
        options["authenticator_selection"].user_verification = UserVerificationRequirement.REQUIRED
        return options

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
