"""Activation codes (card T11)."""

from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from accounts.activation_codes import (
    MAX_FAILURES,
    MAX_FAILURES_PER_ADDRESS,
    ActivationError,
    activation_state,
    digest,
    format_code,
    issue_code,
    normalize,
    redeem_code,
    send_code_by_sms,
)
from accounts.models import ActivationCode, ActivationFailure
from accounts.roles import Role
from audit.models import Action, AuditEntry
from sms.providers import memory
from sms.providers.base import SendError

from .helpers import make_user

IP = "192.0.2.10"


class CodeTests(TestCase):
    def setUp(self):
        self.front_desk = make_user("nadia", Role.FRONT_DESK)
        self.awa = make_user("awa", first_name="Awa", phone="+33612345647")

    def test_format_and_storage(self):
        code = issue_code(self.awa, by=self.front_desk)
        self.assertRegex(code, r"^[A-HJKMNP-TV-Z2-9]{5}-[A-HJKMNP-TV-Z2-9]{5}$")
        saved = ActivationCode.objects.get()
        # Only the digest is in the database, never the code.
        self.assertEqual(saved.digest, digest(code))
        self.assertNotIn(normalize(code), saved.digest)
        self.assertEqual(saved.created_by, self.front_desk)
        self.assertAlmostEqual(
            saved.expires_at, timezone.now() + timedelta(hours=72), delta=timedelta(minutes=1)
        )
        entry = AuditEntry.objects.get(action=Action.ACTIVATION_CODE_ISSUED)
        self.assertEqual((entry.actor, entry.target), (self.front_desk, self.awa))
        self.assertTrue(entry.summary().startswith("Valable jusqu'au "))

    def test_lenient_input(self):
        self.assertEqual(normalize(" abcde fghjk "), "ABCDEFGHJK")
        self.assertEqual(normalize("ABCDE-FGHJK"), "ABCDEFGHJK")
        self.assertEqual(format_code("ABCDEFGHJK"), "ABCDE-FGHJK")
        code = issue_code(self.awa)
        self.assertEqual(redeem_code(code.lower().replace("-", " "), IP).user, self.awa)

    def test_single_use(self):
        code = issue_code(self.awa)
        found = redeem_code(code, IP)
        self.assertIsNotNone(ActivationCode.objects.get(pk=found.pk).used_at)
        with self.assertRaisesMessage(ActivationError, "ne marche pas"):
            redeem_code(code, IP)

    def test_new_code_cancels_the_previous_one(self):
        previous = issue_code(self.awa)
        new = issue_code(self.awa)
        with self.assertRaises(ActivationError):
            redeem_code(previous, IP)
        self.assertEqual(redeem_code(new, IP).user, self.awa)

    def test_expired_code(self):
        code = issue_code(self.awa)
        ActivationCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        with self.assertRaises(ActivationError):
            redeem_code(code, IP)

    def test_disabled_account(self):
        code = issue_code(self.awa)
        self.awa.is_active = False
        self.awa.save()
        with self.assertRaises(ActivationError):
            redeem_code(code, IP)

    def test_race_between_two_devices(self):
        code = issue_code(self.awa)
        # The other device used the code between the lookup and the update.
        original = ActivationCode.objects.valid

        def valid_then_used(*args, **kwargs):
            result = list(original(*args, **kwargs))
            ActivationCode.objects.update(used_at=timezone.now())
            return ActivationCode.objects.filter(pk__in=[c.pk for c in result])

        with (
            mock.patch.object(ActivationCode.objects, "valid", valid_then_used),
            self.assertRaises(ActivationError),
        ):
            redeem_code(code, IP)

    def test_limit_per_browser(self):
        code = issue_code(self.awa)
        with self.assertRaises(ActivationError) as ctx:
            redeem_code(code, IP, session_failures=MAX_FAILURES)
        self.assertEqual(ctx.exception.code, "too_many_attempts")
        self.assertEqual(redeem_code(code, IP, session_failures=MAX_FAILURES - 1).user, self.awa)

    def test_limit_per_address(self):
        code = issue_code(self.awa)
        ActivationFailure.objects.bulk_create(
            [ActivationFailure(ip_address=IP) for _ in range(MAX_FAILURES_PER_ADDRESS)]
        )
        with self.assertRaises(ActivationError) as ctx:
            redeem_code(code, IP)  # even the right code is refused for one hour
        self.assertEqual(ctx.exception.code, "too_many_attempts")
        # Another address is not blocked.
        self.assertEqual(redeem_code(code, "192.0.2.99").user, self.awa)
        # After one hour, the address is unblocked.
        ActivationFailure.objects.update(created_at=timezone.now() - timedelta(hours=2))
        self.assertEqual(redeem_code(issue_code(self.awa), IP).user, self.awa)

    def test_a_few_mistakes_on_the_shared_wifi_block_nobody(self):
        code = issue_code(self.awa)
        for _ in range(MAX_FAILURES + 5):  # several residents make a mistake, once each
            with self.assertRaises(ActivationError):
                redeem_code("AAAAA-AAAAA", IP)
        self.assertEqual(redeem_code(code, IP).user, self.awa)

    def test_code_cancelled_during_input(self):
        previous = issue_code(self.awa)
        original = ActivationCode.objects.valid

        calls = []

        def valid_then_new_code(*args, **kwargs):
            if calls:  # later calls (including those of issue_code): normal behaviour
                return original(*args, **kwargs)
            calls.append(1)
            result = list(original(*args, **kwargs))
            issue_code(self.awa)  # the front desk replaces the code at that moment
            return ActivationCode.objects.filter(pk__in=[c.pk for c in result])

        with (
            mock.patch.object(ActivationCode.objects, "valid", valid_then_new_code),
            self.assertRaises(ActivationError),
        ):
            redeem_code(previous, IP)
        self.assertFalse(ActivationCode.objects.filter(used_at__isnull=False).exists())

    def test_cleanup_of_old_failures(self):
        ActivationFailure.objects.create(ip_address=IP)
        ActivationFailure.objects.update(created_at=timezone.now() - timedelta(days=2))
        with self.assertRaises(ActivationError):
            redeem_code("AAAAA-AAAAA", IP)
        self.assertEqual(ActivationFailure.objects.count(), 1)

    def test_digest_depends_on_secret_key(self):
        with self.settings(SECRET_KEY="key-a" * 10):
            a = digest("ABCDEFGHJK")
        with self.settings(SECRET_KEY="key-b" * 10):
            b = digest("ABCDEFGHJK")
        self.assertNotEqual(a, b)

    def test_state(self):
        self.assertEqual(activation_state(self.awa), (None, None))
        code = issue_code(self.awa)
        self.assertEqual(activation_state(self.awa)[1], "active")
        redeem_code(code, IP)
        self.assertEqual(activation_state(self.awa)[1], "used")
        issue_code(self.awa)
        ActivationCode.objects.filter(used_at__isnull=True).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(activation_state(self.awa)[1], "expired")


class CodeBySmsTests(TestCase):
    URL = "https://hjb.exemple/activer/"

    def setUp(self):
        memory.outbox.clear()
        self.awa = make_user("awa", phone="+33612345647")

    def test_send(self):
        self.assertTrue(send_code_by_sms(self.awa, self.URL))
        (sms,) = memory.outbox
        self.assertEqual(sms.number, "+33612345647")
        self.assertRegex(sms.text, r"https://hjb\.exemple/activer/#[A-Z2-9]{5}-[A-Z2-9]{5}")
        self.assertIn("valable 72 h", sms.text)
        self.assertEqual(activation_state(self.awa)[1], "active")

    def test_no_number(self):
        self.assertFalse(send_code_by_sms(make_user("lina"), self.URL))
        self.assertEqual(memory.outbox, [])
        self.assertFalse(ActivationCode.objects.exists())

    def test_failure_cancels_the_code(self):
        with mock.patch(
            "sms.providers.memory.MemoryProvider.send",
            side_effect=SendError("refused", temporary=False),
        ):
            self.assertFalse(send_code_by_sms(self.awa, self.URL))
        self.assertEqual(activation_state(self.awa)[1], "expired")

    def test_uncertain_send_keeps_the_code(self):
        with mock.patch(
            "sms.providers.memory.MemoryProvider.send",
            side_effect=SendError("timeout", uncertain=True),
        ):
            self.assertTrue(send_code_by_sms(self.awa, self.URL))
        self.assertEqual(activation_state(self.awa)[1], "active")
