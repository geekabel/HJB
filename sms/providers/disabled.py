"""No provider: every sending is refused.

This is the production setting as long as DJANGO_SMS_PROVIDER is not set.
Unlike the console, nothing is written: numbers and texts (codes, wifi
passwords) do not end up in the server logs.
"""

from .base import ConfigurationError, SmsProvider


class DisabledProvider(SmsProvider):
    name = "disabled"

    def send(self, number, text):
        raise ConfigurationError(
            "Aucun fournisseur de SMS n'est configuré (variable DJANGO_SMS_PROVIDER)."
        )


class PausedProvider(DisabledProvider):
    """SMS cut by the administration in the settings (card T37b).

    Same name as DisabledProvider: everything that checks for "disabled"
    treats it the same way.
    """

    def send(self, number, text):
        raise ConfigurationError("Les SMS sont coupés dans les réglages de la résidence.")
