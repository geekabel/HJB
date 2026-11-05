"""SMSGate: an Android phone sends the SMS (real trials, low volume).

Docs: https://docs.sms-gate.app ("3rdparty" API, POST /3rdparty/v1/messages,
202 response with the message id). Delivery receipts (card T24): GET
/3rdparty/v1/messages/{id} gives the state of the message and of each
recipient (https://docs.sms-gate.app/features/status-tracking/; field names
checked in the official client, android-sms-gateway 4.3.3, domain.py).
"withDeliveryReport" is true by default. Three modes: local server on the
phone (http://<phone-ip>:8080), cloud (https://api.sms-gate.app) or
private server. Authentication: token (cloud, private) or username and
password shown in the app (the only option in local mode).
"""

import requests

from .base import DeliveryState, Receipt, SendError, SendResult, SmsProvider

# Status codes after which a new attempt later may succeed (SMSGate docs).
TEMPORARY_CODES = {429, 500, 502, 503, 504}

# States of SMSGate (ProcessState) and ours. "Processed" can stay forever
# when Android loses the confirmation (SMSGate docs): our 48 h limit ends it.
STATES = {
    "Pending": DeliveryState.PENDING,
    "Processed": DeliveryState.PENDING,
    "Sent": DeliveryState.PENDING,
    "Cancelling": DeliveryState.PENDING,
    "Delivered": DeliveryState.DELIVERED,
    "Failed": DeliveryState.UNDELIVERED,
    "Cancelled": DeliveryState.UNDELIVERED,
}


class SmsGateProvider(SmsProvider):
    name = "smsgate"
    required_options = ("url",)

    def missing_options(self):
        missing = super().missing_options()
        credentials = self.options.get("username") and self.options.get("password")
        if not (self.options.get("token") or credentials):
            missing.append("token (ou username et password)")
        if self.options.get("sim") and str(self.options["sim"]) not in {"1", "2", "3"}:
            missing.append("sim (1, 2 ou 3)")
        return missing

    can_poll = True

    def tracks_delivery(self):
        return True

    def _auth(self):
        headers, auth = {}, None
        if self.options.get("token"):
            headers["Authorization"] = f"Bearer {self.options['token']}"
        else:
            auth = (self.options["username"], self.options["password"])
        return headers, auth

    def _url(self, path):
        return self.options["url"].rstrip("/") + "/3rdparty/v1/messages" + path

    def send(self, number, text):
        body = {
            "textMessage": {"text": text},
            "phoneNumbers": [number],
            "withDeliveryReport": True,
        }
        if self.options.get("sim"):
            body["simNumber"] = int(self.options["sim"])
        headers, auth = self._auth()
        try:
            response = requests.post(
                self._url(""),
                json=body,
                headers=headers,
                auth=auth,
                timeout=float(self.options.get("timeout", 10)),
            )
        except requests.ConnectionError as error:
            # Connection failed (including connect timeout): nothing was sent.
            raise SendError(
                f"SMSGate est injoignable ({type(error).__name__}).", temporary=True
            ) from error
        except requests.RequestException as error:
            # Read timeout or cut response: the SMS may have been sent.
            raise SendError(
                f"SMSGate n'a pas répondu à temps ({type(error).__name__}).", uncertain=True
            ) from error

        data = _json(response)
        if 200 <= response.status_code < 300:
            if data.get("id"):
                return SendResult(self.name, str(data["id"]))
            raise SendError(
                "SMSGate a accepté le message sans donner son identifiant.", uncertain=True
            )
        detail = data.get("message", "")
        raise SendError(
            f"SMSGate a refusé l'envoi (code {response.status_code}). {detail}".strip(),
            temporary=response.status_code in TEMPORARY_CODES,
        )

    def receipt(self, message_id):
        headers, auth = self._auth()
        try:
            response = requests.get(
                self._url("/" + requests.utils.quote(message_id, safe="")),
                headers=headers,
                auth=auth,
                timeout=float(self.options.get("timeout", 10)),
            )
        except requests.RequestException as error:
            raise SendError(
                f"SMSGate est injoignable ({type(error).__name__}).", temporary=True
            ) from error
        if response.status_code == 404:
            return Receipt(DeliveryState.UNKNOWN, "SMSGate ne connaît plus ce SMS.")
        if not 200 <= response.status_code < 300:
            raise SendError(
                f"SMSGate n'a pas donné l'état du SMS (code {response.status_code}).",
                temporary=response.status_code in TEMPORARY_CODES,
            )
        data = _json(response)
        # One number per message: its state, or the state of the message.
        recipients = data.get("recipients")
        first = recipients[0] if isinstance(recipients, list) and recipients else {}
        first = first if isinstance(first, dict) else {}
        state = STATES.get(first.get("state") or data.get("state"))
        if state is None:
            raise SendError("État du SMS illisible dans la réponse de SMSGate.")
        detail = ""
        if state == DeliveryState.UNDELIVERED:
            error = str(first.get("error") or "")[:150]
            detail = f"Le téléphone d'envoi signale un échec{f' : {error}' if error else ''}."
        return Receipt(state, detail)


def _json(response):
    """The JSON body if it is an object, otherwise an empty dict."""
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}
