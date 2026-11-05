"""Providers: network calls are mocked, no SMS is sent."""

import io
from unittest import mock

import requests
from django.test import SimpleTestCase
from ovh import exceptions as ovh_exceptions

from sms.providers.base import ConfigurationError, SendError
from sms.providers.console import ConsoleProvider
from sms.providers.disabled import DisabledProvider
from sms.providers.ovh import OvhProvider
from sms.providers.smsgate import SmsGateProvider

NUMBER = "+33612345678"


def http_response(code, body=None):
    response = mock.Mock(status_code=code)
    if body is None:
        response.json.side_effect = ValueError("no JSON")
    else:
        response.json.return_value = body
    return response


class DisabledTests(SimpleTestCase):
    def test_refuses_without_writing_anything(self):
        with self.assertRaisesMessage(ConfigurationError, "DJANGO_SMS_PROVIDER"):
            DisabledProvider().send(NUMBER, "Code 123456")


class ConsoleTests(SimpleTestCase):
    def test_writes_to_the_console(self):
        stream = io.StringIO()
        result = ConsoleProvider(stream=stream).send(NUMBER, "Bonjour")
        self.assertIn("SMS to +33612345678 (GSM-7, 1 segment)", stream.getvalue())
        self.assertIn("Bonjour", stream.getvalue())
        self.assertEqual(result.provider, "console")


class SmsGateTests(SimpleTestCase):
    def provider(self, **options):
        return SmsGateProvider(
            **({"url": "http://192.0.2.5:8080/", "username": "u", "password": "p"} | options)
        )

    @mock.patch("sms.providers.smsgate.requests.post")
    def test_send_local_mode(self, post):
        post.return_value = http_response(202, {"id": "abc123", "status": "queued"})
        result = self.provider(sim="2").send(NUMBER, "Bonjour")
        self.assertEqual((result.provider, result.message_id), ("smsgate", "abc123"))
        (url,) = post.call_args.args
        self.assertEqual(url, "http://192.0.2.5:8080/3rdparty/v1/messages")
        kwargs = post.call_args.kwargs
        self.assertEqual(
            kwargs["json"],
            {"textMessage": {"text": "Bonjour"}, "phoneNumbers": [NUMBER], "simNumber": 2},
        )
        self.assertEqual(kwargs["auth"], ("u", "p"))
        self.assertEqual(kwargs["timeout"], 10.0)

    @mock.patch("sms.providers.smsgate.requests.post")
    def test_send_with_token(self, post):
        post.return_value = http_response(202, {"id": "x"})
        self.provider(url="https://api.sms-gate.app", token="J").send(NUMBER, "Bonjour")
        self.assertEqual(post.call_args.kwargs["headers"], {"Authorization": "Bearer J"})
        self.assertIsNone(post.call_args.kwargs["auth"])

    @mock.patch("sms.providers.smsgate.requests.post")
    def test_errors(self, post):
        cases = [
            (http_response(400, {"message": "Invalid phone number format"}), False, "code 400"),
            (http_response(401, None), False, "code 401"),
            (http_response(429, {"message": "Too many"}), True, "code 429"),
            (http_response(503, None), True, "code 503"),
            (http_response(500, ["list"]), True, "code 500"),
        ]
        for response, temporary, excerpt in cases:
            with self.subTest(code=response.status_code):
                post.return_value = response
                with self.assertRaisesMessage(SendError, excerpt) as ctx:
                    self.provider().send(NUMBER, "Bonjour")
                self.assertEqual(ctx.exception.temporary, temporary)
                self.assertFalse(ctx.exception.uncertain)

    @mock.patch("sms.providers.smsgate.requests.post")
    def test_accepted_without_id_is_uncertain(self, post):
        for body in ({"status": "queued"}, ["list"], None):
            with self.subTest(body=body):
                post.return_value = http_response(202, body)
                with self.assertRaises(SendError) as ctx:
                    self.provider().send(NUMBER, "Bonjour")
                # The SMS may have been sent: no automatic new attempt.
                self.assertTrue(ctx.exception.uncertain)
                self.assertFalse(ctx.exception.temporary)

    @mock.patch("sms.providers.smsgate.requests.post")
    def test_read_timeout(self, post):
        post.side_effect = requests.ReadTimeout("slow")
        with self.assertRaisesMessage(SendError, "n'a pas répondu à temps") as ctx:
            self.provider().send(NUMBER, "Bonjour")
        self.assertTrue(ctx.exception.uncertain)
        self.assertFalse(ctx.exception.temporary)
        post.side_effect = requests.ConnectTimeout("connect")
        with self.assertRaises(SendError) as ctx:
            self.provider().send(NUMBER, "Bonjour")
        self.assertTrue(ctx.exception.temporary)

    @mock.patch("sms.providers.smsgate.requests.post")
    def test_phone_unreachable(self, post):
        post.side_effect = requests.ConnectionError("refused")
        with self.assertRaisesMessage(SendError, "injoignable") as ctx:
            self.provider().send(NUMBER, "Bonjour")
        self.assertTrue(ctx.exception.temporary)

    def test_missing_options(self):
        self.assertEqual(
            SmsGateProvider().missing_options(),
            ["url", "token (ou username et password)"],
        )
        self.assertEqual(self.provider().missing_options(), [])
        self.assertEqual(SmsGateProvider(url="u", token="j").missing_options(), [])
        self.assertEqual(
            SmsGateProvider(url="u", token="j", sim="SIM1").missing_options(),
            ["sim (1, 2 ou 3)"],
        )


OVH_OPTIONS = {
    "service": "sms-ab12345-1",
    "application_key": "ak",
    "application_secret": "as",
    "consumer_key": "ck",
}


class OvhTests(SimpleTestCase):
    def provider(self, **options):
        return OvhProvider(**(OVH_OPTIONS | options))

    @mock.patch("ovh.Client")
    def test_send(self, client):
        client.return_value.post.return_value = {
            "totalCreditsRemoved": 1,
            "invalidReceivers": [],
            "ids": [27814656],
            "validReceivers": [NUMBER],
        }
        result = self.provider().send(NUMBER, "Bonjour")
        self.assertEqual((result.provider, result.message_id), ("ovh", "27814656"))
        client.assert_called_once_with(
            endpoint="ovh-eu",
            application_key="ak",
            application_secret="as",
            consumer_key="ck",
            timeout=10.0,
        )
        (path,) = client.return_value.post.call_args.args
        self.assertEqual(path, "/sms/sms-ab12345-1/jobs")
        self.assertEqual(
            client.return_value.post.call_args.kwargs,
            {
                "message": "Bonjour",
                "receivers": [NUMBER],
                "charset": "UTF-8",
                "priority": "high",
                "noStopClause": True,
                "senderForResponse": True,
            },
        )

    @mock.patch("ovh.Client")
    def test_declared_sender(self, client):
        client.return_value.post.return_value = {"ids": [1], "invalidReceivers": []}
        self.provider(sender="HJB").send(NUMBER, "Bonjour")
        body = client.return_value.post.call_args.kwargs
        self.assertEqual(body["sender"], "HJB")
        self.assertNotIn("senderForResponse", body)

    @mock.patch("ovh.Client")
    def test_number_refused(self, client):
        client.return_value.post.return_value = {"ids": [], "invalidReceivers": [NUMBER]}
        with self.assertRaisesMessage(SendError, "a refusé ce numéro") as ctx:
            self.provider().send(NUMBER, "Bonjour")
        self.assertFalse(ctx.exception.temporary)

    @mock.patch("ovh.Client")
    def test_api_errors(self, client):
        def response(code):
            return mock.Mock(status_code=code, headers={})

        # (error, temporary, uncertain)
        cases = [
            (ovh_exceptions.HTTPError("x", requests.ConnectionError("refused")), True, False),
            (ovh_exceptions.HTTPError("x", requests.ReadTimeout("slow")), False, True),
            (ovh_exceptions.NetworkError(), False, True),
            (ovh_exceptions.InvalidResponse("x"), False, True),
            (ovh_exceptions.InvalidCredential("key", response=response(403)), False, False),
            (ovh_exceptions.BadParametersError("parameter", response=response(400)), False, False),
            (ovh_exceptions.APIError("too many requests", response=response(429)), True, False),
            (ovh_exceptions.APIError("outage", response=response(500)), True, False),
        ]
        for error, temporary, uncertain in cases:
            with self.subTest(error=f"{type(error).__name__} {error.args[:1]}"):
                client.return_value.post.side_effect = error
                with self.assertRaises(SendError) as ctx:
                    self.provider().send(NUMBER, "Bonjour")
                self.assertEqual(
                    (ctx.exception.temporary, ctx.exception.uncertain), (temporary, uncertain)
                )

    @mock.patch("ovh.Client")
    def test_unexpected_response(self, client):
        client.return_value.post.return_value = ["not", "an", "object"]
        with self.assertRaises(SendError) as ctx:
            self.provider().send(NUMBER, "Bonjour")
        self.assertTrue(ctx.exception.uncertain)

    def test_unknown_region(self):
        with self.assertRaises(ConfigurationError):
            self.provider(endpoint="ovh-mars").send(NUMBER, "Bonjour")

    def test_missing_options(self):
        self.assertEqual(
            OvhProvider(service="s").missing_options(),
            ["application_key", "application_secret", "consumer_key"],
        )
