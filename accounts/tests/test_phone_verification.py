"""Phone verification by SMS code (card T12)."""

import re
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from accounts import phone_verification as v
from accounts.models import PhoneVerification, User
from sms.providers import memory
from sms.providers.base import SendError

from .helpers import make_user


def last_code():
    return re.search(r"\b(\d{6})\b", memory.outbox[-1].text).group(1)


def age(seconds):
    """Act as if the sends happened ``seconds`` earlier."""
    PhoneVerification.objects.update(created_at=timezone.now() - timedelta(seconds=seconds))


class SendTests(TestCase):
    def setUp(self):
        memory.outbox.clear()
        self.awa = make_user("awa", phone="+33612345647")

    def test_send(self):
        verification = v.send_code(self.awa)
        (sms,) = memory.outbox
        self.assertEqual(sms.number, "+33612345647")
        code = last_code()
        self.assertIn("expire dans 10 minutes", sms.text)
        self.assertNotIn(code, verification.digest)
        self.assertEqual(verification.phone, "+33612345647")
        self.assertAlmostEqual(
            verification.expires_at, timezone.now() + v.DURATION, delta=timedelta(seconds=5)
        )

    def test_no_number(self):
        with self.assertRaisesMessage(v.VerificationError, "Aucun numéro"):
            v.send_code(make_user("lina"))

    def test_delay_before_resend(self):
        v.send_code(self.awa)
        with self.assertRaises(v.VerificationError) as ctx:
            v.send_code(self.awa)
        self.assertEqual(ctx.exception.code, "too_soon")
        self.assertTrue(0 < ctx.exception.details["wait"] <= 60)
        age(61)
        v.send_code(self.awa)
        self.assertEqual(len(memory.outbox), 2)

    def test_three_sends_per_hour(self):
        for _ in range(v.SENDS_PER_HOUR):
            v.send_code(self.awa)
            age(61)
        with self.assertRaises(v.VerificationError) as ctx:
            v.send_code(self.awa)
        self.assertEqual(ctx.exception.code, "too_many_sends")
        age(3601)
        v.send_code(self.awa)

    def test_new_code_replaces_the_previous_one(self):
        v.send_code(self.awa)
        previous = last_code()
        age(61)
        v.send_code(self.awa)
        new = last_code()
        if previous != new:
            with self.assertRaises(v.VerificationError):
                v.check_code(self.awa, previous)
        v.check_code(self.awa, new)

    def test_sms_refused(self):
        with (
            mock.patch(
                "sms.providers.memory.MemoryProvider.send",
                side_effect=SendError("refused"),
            ),
            self.assertRaises(v.VerificationError) as ctx,
        ):
            v.send_code(self.awa)
        self.assertEqual(ctx.exception.code, "sms")
        self.assertFalse(PhoneVerification.objects.filter(expires_at__gt=timezone.now()))


class CheckTests(TestCase):
    def setUp(self):
        memory.outbox.clear()
        self.awa = make_user("awa", phone="+33612345647")
        v.send_code(self.awa)
        self.code = last_code()

    def wrong(self):
        return f"{(int(self.code) + 1) % 10**6:06d}"

    def test_right_code(self):
        v.check_code(self.awa, f" {self.code[:3]} {self.code[3:]} ")
        self.awa.refresh_from_db()
        self.assertIsNotNone(self.awa.phone_verified_at)
        with self.assertRaises(v.VerificationError):
            v.check_code(self.awa, self.code)  # single use

    def test_five_attempts(self):
        for remaining in (4, 3, 2, 1):
            with self.assertRaisesMessage(v.VerificationError, f"reste {remaining} essai"):
                v.check_code(self.awa, self.wrong())
        with self.assertRaisesMessage(v.VerificationError, "dernier essai"):
            v.check_code(self.awa, self.wrong())
        # Even the right code no longer works.
        with self.assertRaises(v.VerificationError) as ctx:
            v.check_code(self.awa, self.code)
        self.assertEqual(ctx.exception.code, "too_many_attempts")

    def test_expired_code(self):
        PhoneVerification.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        with self.assertRaisesMessage(v.VerificationError, "expiré"):
            v.check_code(self.awa, self.code)

    def test_number_changed_in_the_meantime(self):
        self.awa.phone = "+33781234588"
        self.awa.save()
        with self.assertRaises(v.VerificationError):
            v.check_code(self.awa, self.code)

    def test_invalid_input_counts_as_an_attempt(self):
        with self.assertRaises(v.VerificationError):
            v.check_code(self.awa, "abc")
        self.assertEqual(PhoneVerification.objects.get().attempts, 1)

    def test_attempts_counted_in_database(self):
        # Two simultaneous requests start from the same state: the counter stays correct.
        PhoneVerification.objects.update(attempts=v.MAX_ATTEMPTS - 1)
        with self.assertRaises(v.VerificationError):
            v.check_code(self.awa, self.wrong())
        with self.assertRaises(v.VerificationError) as ctx:
            v.check_code(self.awa, self.code)
        self.assertEqual(ctx.exception.code, "too_many_attempts")
        self.assertEqual(PhoneVerification.objects.get().attempts, v.MAX_ATTEMPTS)


class NumberChangeTests(TestCase):
    """The verified number is kept: any other number is not verified, whatever
    the way it changed."""

    def setUp(self):
        memory.outbox.clear()
        self.awa = make_user("awa", phone="+33612345647")
        v.send_code(self.awa)
        v.check_code(self.awa, last_code())
        self.assertTrue(User.objects.get(pk=self.awa.pk).phone_is_verified)

    def test_by_save(self):
        awa = User.objects.get(pk=self.awa.pk)
        awa.save(update_fields=["first_name"])
        awa.phone = "+33781234588"
        awa.save(update_fields=["phone"])
        self.assertFalse(User.objects.get(pk=awa.pk).phone_is_verified)

    def test_by_update_or_partial_load(self):
        User.objects.filter(pk=self.awa.pk).update(phone="+33781234588")
        self.assertFalse(User.objects.get(pk=self.awa.pk).phone_is_verified)
        awa = User.objects.only("username").get(pk=self.awa.pk)
        awa.phone = "+33612345647"
        awa.save()
        # Back to the verified number: verified again, which is correct.
        self.assertTrue(User.objects.get(pk=self.awa.pk).phone_is_verified)

    def test_stale_instance_does_not_erase_a_verification(self):
        stale = User.objects.get(pk=self.awa.pk)
        stale.refresh_from_db()
        stale.first_name = "Awa"
        stale.save()
        self.assertTrue(User.objects.get(pk=self.awa.pk).phone_is_verified)

    def test_send_under_lock(self):
        # Send limits are checked after locking the account row.
        age(61)
        with mock.patch.object(
            User.objects, "select_for_update", wraps=User.objects.select_for_update
        ) as lock:
            v.send_code(self.awa)
        lock.assert_called_once()
