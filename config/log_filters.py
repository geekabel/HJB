"""Logging filters for production (card T38)."""

import logging
import re

# The secret in the address of the OVH delivery receipts (card T24).
OVH_SECRET = re.compile(r"/sms/ovh/[^/?\s]+")


class HideSecretPaths(logging.Filter):
    """Replace the secret part of an address in a log line.

    django.request writes the path of a refused request ("Not Found: ...");
    the secret of the OVH receipts must never reach the journal.
    """

    def filter(self, record):
        if isinstance(record.msg, str):
            record.msg = OVH_SECRET.sub("/sms/ovh/REDACTED", record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                OVH_SECRET.sub("/sms/ovh/REDACTED", arg) if isinstance(arg, str) else arg
                for arg in record.args
            )
        return True
