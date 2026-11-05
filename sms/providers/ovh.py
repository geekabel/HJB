"""OVHcloud: production provider.

Docs:
- sending through the API: https://docs.ovhcloud.com/fr/guides/web-cloud/messaging/sms/sending-via-api-c.md
  (POST /sms/{serviceName}/jobs; rights GET /sms/, GET /sms/*/jobs, POST /sms/*/jobs)
- request signing: done by the official python-ovh library,
  as OVHcloud advises (https://github.com/ovh/python-ovh).

Delivery receipts (card T24): OVHcloud calls the "callback" address of the
API user at each status change, with ``id``, ``ptt`` (status code), ``date``
and ``description`` in the query string
(https://docs.ovhcloud.com/en/guides/web-cloud/messaging/sms/faq-sms and
https://docs.ovhcloud.com/en/guides/web-cloud/messaging/sms/sms-users).
The address is set by hand in the OVHcloud manager (see the README); it holds
a secret (SMS_RECEIPT_SECRET), since the call carries no signature.

``noStopClause``: our messages are service information, not marketing.
Without this option, OVHcloud adds "STOP" and blocks sending
between 8 pm and 8 am (OVHcloud docs).
"""

import requests
from django.conf import settings

from .base import ConfigurationError, DeliveryState, Receipt, SendError, SendResult, SmsProvider

# PTT codes of OVHcloud ("sms-users" guide, non-exhaustive list): on the way.
PENDING_CODES = {1, 2, 3, 24, 25, 26}
DELIVERED_CODE = 4
UNKNOWN_CODE = 6
# The others: it will not arrive. A French reason for the frequent ones.
REASONS = {
    5: "Non distribué, sans précision de l'opérateur.",
    8: "Expiré : le téléphone est resté injoignable.",
    20: "Message non distribuable sous cette forme.",
    21: "Refusé pour une question de crédit.",
    23: "Numéro invalide, bloqué ou interdit.",
    27: "Téléphone incompatible avec ce message.",
    28: "Refusé par l'opérateur comme spam.",
    29: "Contenu refusé par l'opérateur.",
    33: "Bloqué par un contrôle parental.",
    74: "Le destinataire est à l'étranger (itinérance).",
}


def callback_receipt(ptt, description=""):
    """Receipt for the ``ptt`` code sent to the callback address."""
    try:
        code = int(ptt)
    except (TypeError, ValueError):
        return None
    if code == DELIVERED_CODE:
        return Receipt(DeliveryState.DELIVERED)
    if code in PENDING_CODES:
        return Receipt(DeliveryState.PENDING, f"En cours d'acheminement (code {code}).")
    if code == UNKNOWN_CODE:
        return Receipt(DeliveryState.UNKNOWN, "L'opérateur ne dit pas si le SMS est arrivé.")
    reason = REASONS.get(code) or f"Non reçu (code OVHcloud {code})."
    return Receipt(DeliveryState.UNDELIVERED, reason)


class OvhProvider(SmsProvider):
    name = "ovh"
    required_options = ("service", "application_key", "application_secret", "consumer_key")

    def tracks_delivery(self):
        # Only if the callback address can be checked (secret set).
        return bool(getattr(settings, "SMS_RECEIPT_SECRET", ""))

    def _client(self):
        import ovh

        try:
            return ovh.Client(
                endpoint=self.options.get("endpoint") or "ovh-eu",
                application_key=self.options["application_key"],
                application_secret=self.options["application_secret"],
                consumer_key=self.options["consumer_key"],
                timeout=float(self.options.get("timeout", 10)),
            )
        except ovh.exceptions.APIError as error:  # unknown region, inconsistent keys
            raise ConfigurationError(f"Configuration OVHcloud invalide : {error}") from error

    def send(self, number, text):
        from ovh import exceptions

        body = {
            "message": text,
            "receivers": [number],
            "charset": "UTF-8",
            "priority": "high",
            "noStopClause": True,
        }
        if self.options.get("sender"):
            body["sender"] = self.options["sender"]
        else:
            # OVHcloud short number, which also allows receiving replies.
            body["senderForResponse"] = True
        try:
            response = self._client().post(f"/sms/{self.options['service']}/jobs", **body)
        except exceptions.HTTPError as error:
            # The library wraps the requests error (2nd argument).
            cause = error.args[1] if len(error.args) > 1 else None
            if isinstance(cause, requests.ConnectionError):
                raise SendError("OVHcloud est injoignable.", temporary=True) from error
            raise SendError(
                "OVHcloud n'a pas répondu à temps : le SMS est peut-être parti.", uncertain=True
            ) from error
        except (exceptions.NetworkError, exceptions.InvalidResponse) as error:
            raise SendError(
                "Réponse d'OVHcloud illisible : le SMS est peut-être parti.", uncertain=True
            ) from error
        except exceptions.APIError as error:
            status = getattr(getattr(error, "response", None), "status_code", 0) or 0
            raise SendError(
                f"OVHcloud a refusé l'envoi : {error}",
                temporary=status == 429 or status >= 500,
            ) from error

        if not isinstance(response, dict):
            raise SendError("Réponse d'OVHcloud inattendue.", uncertain=True)
        if response.get("invalidReceivers") or not response.get("ids"):
            raise SendError("OVHcloud a refusé ce numéro.", temporary=False)
        return SendResult(self.name, str(response["ids"][0]))
