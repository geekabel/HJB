"""Reminder before the end of a wifi access, and the renewals page (card T17)."""

import io
from datetime import date, timedelta
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user
from push.services import SendResult
from tools.html_capture import save_page

from . import wifi
from .models import Floor, Room, Stay, WifiAccess
from .reminders import message, send_wifi_reminders

SENT = SendResult(sent=1)
NOT_SENT = SendResult()


class ReminderTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.nadia = make_user("nadia", Role.FRONT_DESK, first_name="Nadia")
        f3 = Floor.objects.create(number=3)
        cls.r312 = Room.objects.create(number="312", floor=f3)
        cls.r304 = Room.objects.create(number="304", floor=f3)
        cls.ines = make_user("ines", first_name="Inès", last_name="Martin")
        cls.yanis = make_user("yanis", first_name="Yanis", last_name="Traoré")
        Stay.objects.create(resident=cls.ines, room=cls.r312, arrival=date(2026, 9, 1))
        Stay.objects.create(resident=cls.yanis, room=cls.r304, arrival=date(2026, 9, 1))

    def record(self, room, days_left, username="vre8th"):
        today = timezone.localdate()
        access = wifi.set_access(
            room,
            username=username,
            password="72ptmk",
            expires_on=today + timedelta(days=max(days_left, 1)),
            replaces=wifi.current_access(room),
            by=self.nadia,
        )
        if days_left < 1:
            WifiAccess.objects.filter(pk=access.pk).update(
                created_on=today - timedelta(days=400), expires_on=today + timedelta(days=days_left)
            )
            access.refresh_from_db()
        return access


@mock.patch("housing.reminders.send_to_user", return_value=SENT)
class SendTests(ReminderTestCase):
    def test_fifteen_days_before(self, send):
        due = self.record(self.r312, 15)
        self.record(self.r304, 16, username="k3pzqa")  # too early
        result = send_wifi_reminders()
        self.assertEqual(result.sent, 1)
        send.assert_called_once()
        self.assertEqual(send.call_args.args, (self.ines,))
        kwargs = send.call_args.kwargs
        self.assertEqual(kwargs["title"], "Votre wifi se termine bientôt")
        self.assertIn("dans 15 jours", kwargs["body"])
        self.assertEqual((kwargs["url"], kwargs["tag"]), ("/wifi/", "wifi-expiry"))
        due.refresh_from_db()
        self.assertIsNotNone(due.reminder_sent_at)

    def test_only_once(self, send):
        self.record(self.r312, 10)
        send_wifi_reminders()
        send_wifi_reminders()
        self.assertEqual(send.call_count, 1)

    def test_catch_up_when_a_day_was_missed(self, send):
        self.record(self.r312, 9)
        self.assertEqual(send_wifi_reminders().sent, 1)

    def test_expired_access_gets_no_reminder(self, send):
        self.record(self.r312, -1)
        self.assertEqual(send_wifi_reminders().sent, 0)
        send.assert_not_called()

    def test_reminder_turned_off(self, send):
        self.ines.wifi_expiry_reminder = False
        self.ines.save()
        self.record(self.r312, 5)
        self.assertEqual(send_wifi_reminders().reminder_off, 1)
        send.assert_not_called()

    def test_retried_when_no_device_was_reached(self, send):
        access = self.record(self.r312, 12)
        send.return_value = NOT_SENT
        self.assertEqual(send_wifi_reminders().not_delivered, 1)
        access.refresh_from_db()
        self.assertIsNone(access.reminder_sent_at)
        # The resident turns notifications on the next day: the reminder leaves then.
        send.return_value = SENT
        self.assertEqual(send_wifi_reminders().sent, 1)

    def test_renewal_starts_a_new_reminder(self, send):
        self.record(self.r312, 10)
        send_wifi_reminders()
        new = self.record(self.r312, 365)
        self.assertIsNone(new.reminder_sent_at)

    def test_command(self, send):
        self.record(self.r312, 3)
        out = io.StringIO()
        call_command("send_wifi_reminders", stdout=out)
        self.assertIn("Rappels envoyés : 1.", out.getvalue())


class MessageTests(ReminderTestCase):
    def test_wording(self):
        today = timezone.localdate()
        for days, words in ((0, "aujourd'hui"), (1, "demain"), (7, "dans 7 jours")):
            access = WifiAccess(expires_on=today + timedelta(days=days))
            self.assertIn(f"se termine {words}, le", message(access, today)[1])


class ResidentToggleTests(ReminderTestCase):
    def test_turn_off_and_on(self):
        self.record(self.r312, 200)
        log_in_verified(self.client, self.ines)
        page = self.client.get(reverse("housing:my_wifi"))
        save_page("housing-my-wifi-reminder", page)
        self.assertContains(page, "Me prévenir avant la fin")
        self.assertContains(page, "activez les notifications")  # no device yet
        response = self.client.post(
            reverse("housing:my_wifi_reminder"), {"reminder": "off"}, follow=True
        )
        self.assertContains(response, "Rappel désactivé.")
        self.ines.refresh_from_db()
        self.assertFalse(self.ines.wifi_expiry_reminder)
        response = self.client.post(
            reverse("housing:my_wifi_reminder"), {"reminder": "on"}, follow=True
        )
        self.assertContains(response, "15 jours avant la fin")
        self.ines.refresh_from_db()
        self.assertTrue(self.ines.wifi_expiry_reminder)

    def test_post_only(self):
        log_in_verified(self.client, self.ines)
        self.assertEqual(self.client.get(reverse("housing:my_wifi_reminder")).status_code, 405)


class RenewalsPageTests(ReminderTestCase):
    def test_list(self):
        self.record(self.r312, 12)
        self.record(self.r304, -3, username="k3pzqa")
        far = Room.objects.create(number="305", floor=self.r312.floor)
        lucas = make_user("lucas")
        Stay.objects.create(resident=lucas, room=far, arrival=date(2026, 9, 1))
        self.record(far, 200, username="far001")
        log_in_verified(self.client, self.nadia)
        response = self.client.get(reverse("residents:wifi_renewals"))
        save_page("residents-wifi-renewals", response)
        accesses = list(response.context["accesses"])
        self.assertEqual([a.room.number for a in accesses], ["304", "312"])  # most urgent first
        self.assertContains(response, "Expiré")
        self.assertContains(response, "dans 12 j")
        self.assertNotContains(response, "305")
        self.assertNotContains(response, "vre8th")  # never the username nor the password
        self.assertContains(response, reverse("residents:wifi_access", args=[self.ines.pk]))
        listing = self.client.get(reverse("residents:list"))
        self.assertContains(listing, "2 accès wifi à renouveler")

    def test_educator_sees_without_renew_link(self):
        self.record(self.r312, 12)
        log_in_verified(self.client, make_user("sam", Role.EDUCATOR))
        response = self.client.get(reverse("residents:wifi_renewals"))
        self.assertContains(response, "Inès Martin")
        self.assertNotContains(response, "Renouveler")

    def test_empty(self):
        log_in_verified(self.client, self.nadia)
        response = self.client.get(reverse("residents:wifi_renewals"))
        save_page("residents-wifi-renewals-empty", response)
        self.assertContains(response, "Aucun accès à renouveler")

    def test_resident_refused(self):
        log_in_verified(self.client, self.ines)
        self.assertEqual(self.client.get(reverse("residents:wifi_renewals")).status_code, 403)
