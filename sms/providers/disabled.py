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
