"""SMSGate: an Android phone sends the SMS (real trials, low volume).

Docs: https://docs.sms-gate.app ("3rdparty" API, POST /3rdparty/v1/messages,
202 response with the message id). Three modes: local server on the
phone (http://<phone-ip>:8080), cloud (https://api.sms-gate.app) or
private server. Authentication: token (cloud, private) or username and
password shown in the app (the only option in local mode).
"""

import requests

from .base import SendError, SendResult, SmsProvider

# Status codes after which a new attempt later may succeed (SMSGate docs).
TEMPORARY_CODES = {429, 500, 502, 503, 504}


class SmsGateProvider(SmsProvider):
    name = "smsgate"
    required_options = ("url",)

    def missing_options(self):
        missing = super().missing_options()
        credentials = self.options.get("username") and self.options.get("password")
        if not (self.options.get("token") or credentials):
            missing.append("token (or username and password)")
        if self.options.get("sim") and str(self.options["sim"]) not in {"1", "2", "3"}:
            missing.append("sim (1, 2 or 3)")
        return missing

    def send(self, number, text):
        body = {"textMessage": {"text": text}, "phoneNumbers": [number]}
        if self.options.get("sim"):
            body["simNumber"] = int(self.options["sim"])
        headers, auth = {}, None
        if self.options.get("token"):
            headers["Authorization"] = f"Bearer {self.options['token']}"
        else:
            auth = (self.options["username"], self.options["password"])
        url = self.options["url"].rstrip("/") + "/3rdparty/v1/messages"
        try:
            response = requests.post(
                url,
                json=body,
                headers=headers,
                auth=auth,
                timeout=float(self.options.get("timeout", 10)),
            )
        except requests.ConnectionError as error:
            # Connection failed (including connect timeout): nothing was sent.
            raise SendError(
                f"SMSGate is unreachable ({type(error).__name__}).", temporary=True
            ) from error
        except requests.RequestException as error:
            # Read timeout or cut response: the SMS may have been sent.
            raise SendError(
                f"SMSGate did not respond in time ({type(error).__name__}).", uncertain=True
            ) from error

        data = _json(response)
        if 200 <= response.status_code < 300:
            if data.get("id"):
                return SendResult(self.name, str(data["id"]))
            raise SendError("SMSGate accepted the message without giving its id.", uncertain=True)
        detail = data.get("message", "")
        raise SendError(
            f"SMSGate refused the sending (code {response.status_code}). {detail}".strip(),
            temporary=response.status_code in TEMPORARY_CODES,
        )


def _json(response):
    """The JSON body if it is an object, otherwise an empty dict."""
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}
