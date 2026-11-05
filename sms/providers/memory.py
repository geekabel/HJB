"""Test provider: the SMS are kept in memory, in ``outbox``.

The project test runner (tools/test_runner.py) sets it for every test,
like Django does for e-mails (``mail.outbox``): no test can send a real SMS.
"""

import uuid
from dataclasses import dataclass

from .base import SendResult, SmsProvider


@dataclass(frozen=True)
class SentSms:
    number: str
    text: str
    message_id: str


outbox = []


class MemoryProvider(SmsProvider):
    name = "memory"

    def send(self, number, text):
        message_id = uuid.uuid4().hex
        outbox.append(SentSms(number, text, message_id))
        return SendResult(self.name, message_id)
