"""Development provider: the SMS is written to the console, nothing is sent."""

import sys
import uuid

from ..segments import analyze
from .base import SendResult, SmsProvider


class ConsoleProvider(SmsProvider):
    name = "console"

    def send(self, number, text):
        info = analyze(text)
        stream = self.options.get("stream") or sys.stdout
        stream.write(
            f"--- SMS to {number} ({info.encoding}, {info.segments} segment"
            f"{'s' if info.segments > 1 else ''}) ---\n{text}\n---\n"
        )
        stream.flush()
        return SendResult(self.name, uuid.uuid4().hex)
