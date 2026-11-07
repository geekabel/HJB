"""The daily SMS limit of the residence settings."""

from datetime import date
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from accounts.activation_codes import send_code_by_sms
from accounts.phone_verification import VerificationError, send_code
from accounts.tests.helpers import make_user
from residence.models import ResidenceSettings
from sms.models import SmsDailyUsage
from sms.providers import memory
from sms.providers.base import SendError, SmsError
from sms.service import (
    DEFAULT_DAILY_LIMIT,
    KEPT_FOR_CODES,
    DailyLimitReached,
    daily_limit,
    left_today,
    send_sms,
    sent_today,
)

NUMBER = "+33612345678"


def set_limit(value):
    ResidenceSettings.objects.update_or_create(pk=1, defaults={"sms_daily_limit": value})


class DailyLimitTests(TestCase):
    def setUp(self):
        memory.outbox.clear()

    def test_default_is_100(self):
        self.assertEqual(daily_limit(), DEFAULT_DAILY_LIMIT)
        self.assertEqual(DEFAULT_DAILY_LIMIT, 100)
        self.assertEqual(ResidenceSettings.load().sms_daily_limit, 100)

    def test_counts_and_stops_at_the_limit(self):
        set_limit(20)  # 10 for the messages, the last 10 kept for the codes
        for _ in range(10):
            send_sms(NUMBER, "Bonjour")
        self.assertEqual((sent_today(), left_today()), (10, 0))
        with (
            self.assertLogs("sms.service", "WARNING"),
            self.assertRaisesMessage(DailyLimitReached, "Limite de 10 SMS par jour") as ctx,
        ):
            send_sms(NUMBER, "Bonjour")
        self.assertFalse(ctx.exception.temporary)
        self.assertFalse(ctx.exception.uncertain)
        self.assertEqual(len(memory.outbox), 10)
        # The codes still leave, up to the real limit.
        for _ in range(KEPT_FOR_CODES):
            send_sms(NUMBER, "Code 123456", code=True)
        with self.assertLogs("sms.service", "WARNING"), self.assertRaises(DailyLimitReached):
            send_sms(NUMBER, "Code 123456", code=True)
        self.assertEqual((sent_today(), len(memory.outbox)), (20, 20))

    def test_a_long_message_counts_for_each_segment(self):
        set_limit(20)
        send_sms(NUMBER, "a" * 153 * 4)  # 4 SMS
        self.assertEqual(sent_today(), 4)
        send_sms(NUMBER, "a" * 153 * 6)  # 6 SMS + 4 = 10: fits
        with self.assertLogs("sms.service", "WARNING"), self.assertRaises(DailyLimitReached):
            send_sms(NUMBER, "Bonjour")  # 11: refused
        self.assertEqual(sent_today(), 10)

    def test_a_failed_sms_no_longer_counts(self):
        with (
            mock.patch("sms.providers.memory.MemoryProvider.send", side_effect=SendError("refusé")),
            self.assertLogs("sms.service", "WARNING"),
            self.assertRaises(SendError),
        ):
            send_sms(NUMBER, "Bonjour")
        self.assertEqual(sent_today(), 0)

    def test_an_uncertain_sms_still_counts(self):
        with (
            mock.patch(
                "sms.providers.memory.MemoryProvider.send",
                side_effect=SendError("peut-être parti", uncertain=True),
            ),
            self.assertLogs("sms.service", "WARNING"),
            self.assertRaises(SendError),
        ):
            send_sms(NUMBER, "Bonjour")
        self.assertEqual(sent_today(), 1)

    def test_an_unexpected_error_still_counts(self):
        # The provider may have sent it before failing: like "uncertain".
        with (
            mock.patch("sms.providers.memory.MemoryProvider.send", side_effect=RuntimeError),
            self.assertRaises(RuntimeError),
        ):
            send_sms(NUMBER, "Bonjour")
        self.assertEqual(sent_today(), 1)

    def test_a_new_day_starts_again(self):
        set_limit(20)
        SmsDailyUsage.objects.create(day=date(2026, 11, 6), segments=20)
        with mock.patch("sms.service.timezone.localdate", return_value=date(2026, 11, 6)):
            self.assertEqual(left_today(), 0)
        with mock.patch("sms.service.timezone.localdate", return_value=date(2026, 11, 7)):
            send_sms(NUMBER, "Bonjour")
        self.assertEqual(SmsDailyUsage.objects.get(day=date(2026, 11, 7)).segments, 1)

    def test_a_paused_service_does_not_count_and_says_why(self):
        set_limit(20)
        SmsDailyUsage.objects.create(day=timezone.localdate(), segments=20)
        ResidenceSettings.objects.update_or_create(pk=1, defaults={"sms_provider": "paused"})
        with (
            self.assertLogs("sms.service", "WARNING"),
            self.assertRaisesMessage(SmsError, "coupés"),
        ):
            send_sms(NUMBER, "Bonjour")
        self.assertEqual(sent_today(), 20)

    def test_verification_code_says_why(self):
        set_limit(20)
        SmsDailyUsage.objects.create(day=timezone.localdate(), segments=20)
        user = make_user("lea", phone=NUMBER)
        with (
            self.assertLogs("sms.service", "WARNING"),
            self.assertRaisesMessage(VerificationError, "Plus aucun SMS ne peut partir"),
        ):
            send_code(user)
        self.assertEqual(memory.outbox, [])


class CodesTests(TestCase):
    def test_codes_use_the_share_kept_for_them(self):
        set_limit(20)
        SmsDailyUsage.objects.create(day=timezone.localdate(), segments=10)  # messages: none left
        memory.outbox.clear()
        user = make_user("lea", phone=NUMBER)
        send_code(user)
        self.assertEqual(len(memory.outbox), 1)
        self.assertTrue(
            send_code_by_sms(make_user("tom", phone="+33698765432"), "https://hjb.test/a/")
        )
        self.assertEqual(sent_today(), 12)
