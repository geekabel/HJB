import logging

from django.test import SimpleTestCase

from config.log_filters import HideSecretPaths


class HideSecretPathsTests(SimpleTestCase):
    def test_the_ovh_secret_never_reaches_the_log(self):
        record = logging.LogRecord(
            "django.request",
            logging.WARNING,
            __file__,
            1,
            "%s: %s",
            ("Not Found", "/sms/ovh/abcDEF123_secret/"),
            None,
        )
        HideSecretPaths().filter(record)
        self.assertEqual(record.getMessage(), "Not Found: /sms/ovh/REDACTED/")
        record = logging.LogRecord(
            "x", logging.WARNING, __file__, 1, "GET /sms/ovh/s3cr3t?id=1", None, None
        )
        HideSecretPaths().filter(record)
        self.assertEqual(record.getMessage(), "GET /sms/ovh/REDACTED?id=1")
