"""Common interface of the SMS providers.

Each provider receives its OPTIONS (``SMS`` setting) as keyword arguments
and implements ``send(number, text)``. The rest of the application only
knows this interface: changing provider only changes the setting.
"""

from dataclasses import dataclass
from datetime import datetime


class SmsError(Exception):
    """SMS sending error. Unless ``uncertain`` is true, the SMS was not sent.

    ``temporary``: true if a new attempt later may succeed (network down
    before sending, overload). False if the same sending will fail again.
    ``uncertain``: the provider may have sent the SMS (timeout while waiting
    for the response...). Never retry automatically: risk of a duplicate.
    Retries (card T21) rely on these two flags.
    """

    temporary = False
    uncertain = False


class ConfigurationError(SmsError):
    """The provider is badly configured (missing credential...)."""


class SendError(SmsError):
    """The provider refused the sending, or we do not know if it sent it."""

    def __init__(self, message, *, temporary=False, uncertain=False):
        super().__init__(message)
        self.temporary = temporary
        self.uncertain = uncertain


@dataclass(frozen=True)
class SendResult:
    provider: str
    message_id: str  # id of the message at the provider, to follow its delivery
    # A delivery receipt will come (card T24): set by send_sms().
    tracked: bool = False


class DeliveryState:
    """Delivery receipt of an SMS (card T24), the same for every provider."""

    PENDING = "pending"  # on its way: accepted, not yet on the phone
    DELIVERED = "delivered"  # the phone received it
    UNDELIVERED = "undelivered"  # it will not arrive
    UNKNOWN = "unknown"  # the operator does not say
    FINAL = (DELIVERED, UNDELIVERED, UNKNOWN)


@dataclass(frozen=True)
class Receipt:
    state: str  # a DeliveryState value
    detail: str = ""  # French, shown to the staff
    at: datetime | None = None


class SmsProvider:
    name = "?"
    # Required options: checked by the configuration check (sms/checks.py).
    required_options = ()

    def __init__(self, **options):
        self.options = options

    def missing_options(self):
        return [name for name in self.required_options if not self.options.get(name)]

    def send(self, number, text):
        """Send ``text`` to the E.164 number ``number``. Return a SendResult.

        Raise SendError if the SMS was not sent.
        """
        raise NotImplementedError

    # Delivery receipts (card T24). A provider either answers when asked
    # (receipt(), "pull"), or calls the site itself ("push", OVHcloud).
    can_poll = False

    def tracks_delivery(self):
        """True if a receipt will come for the SMS sent now."""
        return False

    def receipt(self, message_id):
        """The Receipt of a sent SMS, asked to the provider. SmsError if it fails."""
        raise NotImplementedError
