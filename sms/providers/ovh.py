"""OVHcloud: production provider.

Docs:
- sending through the API: https://docs.ovhcloud.com/fr/guides/web-cloud/messaging/sms/sending-via-api-c.md
  (POST /sms/{serviceName}/jobs; rights GET /sms/, GET /sms/*/jobs, POST /sms/*/jobs)
- request signing: done by the official python-ovh library,
  as OVHcloud advises (https://github.com/ovh/python-ovh).

``noStopClause``: our messages are service information, not marketing.
Without this option, OVHcloud adds "STOP" and blocks sending
between 8 pm and 8 am (OVHcloud docs).
"""

import requests

from .base import ConfigurationError, SendError, SendResult, SmsProvider


class OvhProvider(SmsProvider):
    name = "ovh"
    required_options = ("service", "application_key", "application_secret", "consumer_key")

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
