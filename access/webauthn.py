"""Settings for the WebAuthn ceremonies (django-otp-webauthn library).

The "helper" class is the intended place to adapt the library:
https://django-otp-webauthn.readthedocs.io/en/stable/how_to_guides/customize_helper_class.html
All the cryptography stays in py_webauthn, called by the library.
"""

from django_otp_webauthn.helpers import WebAuthnHelper
from webauthn.helpers.structs import UserVerificationRequirement


class HJBWebAuthnHelper(WebAuthnHelper):
    def get_generate_registration_options_kwargs(self, *, user):
        options = super().get_generate_registration_options_kwargs(user=user)
        # Login requires Face ID, a fingerprint or the device PIN. Registration
        # requires it too: otherwise a passkey without verification would be
        # saved (and would replace the others) but could never be used.
        options["authenticator_selection"].user_verification = UserVerificationRequirement.REQUIRED
        return options

    def get_credential_display_name(self, user):
        # Shown by the phone in its passkey list: the name, not the technical identifier.
        return user.get_full_name() or user.get_username()


class ActivationWebAuthnHelper(HJBWebAuthnHelper):
    """For activation: the new passkey replaces the old ones.

    So the existing passkeys are not sent to the browser
    (``excludeCredentials``). Otherwise, a phone that already has a passkey
    for this account would refuse to create a new one.
    """

    def get_generate_registration_options_kwargs(self, *, user):
        options = super().get_generate_registration_options_kwargs(user=user)
        options["exclude_credentials"] = []
        return options
