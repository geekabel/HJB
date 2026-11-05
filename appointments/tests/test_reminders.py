"""Reminders and cancellation of the meetings (card T29)."""

from datetime import date, datetime, time, timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user
from push.services import SendResult
from tools.html_capture import save_page

from .. import availability, booking, reminders
from ..models import Appointment, EducatorSettings
from ..tasks import remind_task

MONDAY = date(2026, 11, 16)
SUNDAY = MONDAY - timedelta(days=1)


def at(day, hour, minute=0):
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


class ReminderTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.samia = make_user("samia", Role.EDUCATOR, first_name="Samia")
        cls.julien = make_user("julien", Role.EDUCATOR, first_name="Julien")
        cls.ines = make_user("ines", first_name="Inès", phone="+33611111111")
        cls.yanis = make_user("yanis", first_name="Yanis")

    def setUp(self):
        self.push = self._patch("appointments.tasks.send_to_user", SendResult(sent=1))
        self.sms = self._patch("appointments.tasks.send_sms", None)
        self.sms_ready = self._patch("messaging.sending.sms_ready", True)

    def _patch(self, target, value):
        patcher = mock.patch(target, return_value=value)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def meeting(self, start, created=None, **kwargs):
        """A confirmed meeting, booked at ``created`` (3 days before, by default)."""
        data = {"educator": self.samia, "resident": self.ines, "start": start}
        data.update(kwargs)
        data.setdefault("end", data["start"] + timedelta(minutes=30))
        meeting = Appointment.objects.create(**data)
        # created_at is auto_now_add: set the booking moment afterwards.
        Appointment.objects.filter(pk=meeting.pk).update(
            created_at=created or start - timedelta(days=3)
        )
        meeting.refresh_from_db()
        return meeting

    def send_due(self, now):
        """run_scheduled at ``now``; the task (run at once in tests) sees the same time."""
        with mock.patch("django.utils.timezone.now", return_value=now):
            return reminders.send_due(now)


class ReminderTests(ReminderTestCase):
    def test_the_day_before_at_six_pm_once(self):
        meeting = self.meeting(at(MONDAY, 10))
        self.assertEqual(self.send_due(at(SUNDAY, 17, 59)), 0)
        self.assertEqual(self.send_due(at(SUNDAY, 18, 0)), 1)
        self.assertEqual(self.send_due(at(SUNDAY, 18, 1)), 0)  # never twice
        user, kwargs = self.push.call_args.args[0], self.push.call_args.kwargs
        self.assertEqual(user, self.ines)
        self.assertEqual(kwargs["title"], "Rappel de rendez-vous")
        self.assertEqual(
            kwargs["body"], "Rendez-vous demain, lundi 16 novembre à 10:00, avec Samia."
        )
        self.assertEqual(kwargs["url"], reverse("rdv:detail", args=[meeting.pk]))
        # Kept for an offline phone until the start, never longer.
        self.assertEqual(kwargs["ttl"], 16 * 3600)
        self.sms.assert_not_called()  # the notification arrived

    def test_sms_only_without_a_device_and_only_the_day_before(self):
        self.push.return_value = SendResult(sent=0)
        self.meeting(at(MONDAY, 10))
        self.send_due(at(SUNDAY, 18))
        self.assertEqual(
            self.sms.call_args.args,
            (
                "+33611111111",
                "HJB : rappel, rendez-vous demain lundi 16 novembre à 10:00 avec Samia.",
            ),
        )
        self.sms.reset_mock()
        self.assertEqual(self.send_due(at(MONDAY, 9)), 1)  # one hour before
        kwargs = self.push.call_args.kwargs
        self.assertEqual(kwargs["title"], "Rendez-vous bientôt")
        self.assertEqual(kwargs["body"], "Rendez-vous aujourd'hui à 10:00 avec Samia.")
        self.sms.assert_not_called()  # no SMS for the hour-before reminder

    def test_no_paid_sms_when_a_device_did_not_answer(self):
        # A device exists but the push service is down: no SMS.
        self.push.return_value = SendResult(failed=1)
        self.meeting(at(MONDAY, 10))
        self.send_due(at(SUNDAY, 18))
        self.sms.assert_not_called()

    def test_no_sms_when_push_is_not_set_up_or_sms_not_ready(self):
        from django.core.exceptions import ImproperlyConfigured

        self.push.side_effect = ImproperlyConfigured
        self.meeting(at(MONDAY, 10))
        self.send_due(at(SUNDAY, 18))
        self.push.side_effect = None
        self.push.return_value = SendResult(sent=0)
        self.sms_ready.return_value = False
        self.meeting(at(MONDAY, 11))
        self.send_due(at(SUNDAY, 18, 1))
        self.sms.assert_not_called()

    def test_no_sms_without_a_phone_nor_to_someone_who_left(self):
        self.push.return_value = SendResult(sent=0)
        self.meeting(at(MONDAY, 10), resident=self.yanis)  # no phone
        self.ines.is_active = False
        self.ines.save(update_fields=["is_active"])
        self.meeting(at(MONDAY, 11))
        self.assertEqual(self.send_due(at(SUNDAY, 18)), 2)
        self.sms.assert_not_called()

    def test_only_in_the_evening(self):
        self.meeting(at(MONDAY, 10))
        self.assertEqual(self.send_due(at(SUNDAY, 21)), 0)  # no SMS at night
        self.assertEqual(self.send_due(at(MONDAY, 7)), 0)  # "demain" would be wrong
        self.assertEqual(self.send_due(at(SUNDAY, 20, 59)), 1)

    def test_booked_on_the_day_or_after_six_pm(self):
        # Booked on Monday at 9:00 for 14:00: no "demain", only the hour before.
        same_day = self.meeting(at(MONDAY, 14), created=at(MONDAY, 9))
        self.assertEqual(self.send_due(at(MONDAY, 9, 1)), 0)
        # Booked on Sunday at 19:00 or 23:30 for Monday: nothing that evening.
        self.meeting(at(MONDAY, 10), created=at(SUNDAY, 19))
        self.meeting(at(MONDAY, 11), created=at(SUNDAY, 23, 30))
        self.assertEqual(self.send_due(at(SUNDAY, 19, 1)), 0)
        self.assertEqual(self.send_due(at(SUNDAY, 23, 31)), 0)
        self.push.assert_not_called()
        self.assertEqual(self.send_due(at(MONDAY, 13)), 1)
        self.assertEqual(
            self.push.call_args.kwargs["url"], reverse("rdv:detail", args=[same_day.pk])
        )

    def test_never_late(self):
        self.meeting(at(MONDAY, 10))
        # The worker stopped all evening: at 8:30 the day-before reminder is useless.
        self.assertEqual(self.send_due(at(MONDAY, 8, 30)), 0)
        # 10 minutes before: the hour-before reminder comes too late to help.
        self.assertEqual(self.send_due(at(MONDAY, 9, 50)), 0)
        # After the start: nothing at all.
        self.assertEqual(self.send_due(at(MONDAY, 10, 1)), 0)
        self.push.assert_not_called()

    def test_the_task_checks_the_time_again(self):
        # Claimed in time, but the queue ran the task late: nothing is sent.
        meeting = self.meeting(at(MONDAY, 10))
        with mock.patch("django.utils.timezone.now", return_value=at(MONDAY, 10, 5)):
            remind_task.call(meeting_id=meeting.pk, kind="hour_before")
        with mock.patch("django.utils.timezone.now", return_value=at(MONDAY, 8)):
            remind_task.call(meeting_id=meeting.pk, kind="day_before")
        self.push.assert_not_called()

    def test_summer_and_winter_time(self):
        # The day before at 18:00, Paris time, on both days the clocks change.
        self.meeting(at(date(2026, 3, 30), 10))
        self.meeting(at(date(2026, 10, 26), 10))
        march = at(date(2026, 3, 29), 18)
        october = at(date(2026, 10, 25), 18)
        self.assertEqual(march.utcoffset(), timedelta(hours=2))
        self.assertEqual(october.utcoffset(), timedelta(hours=1))
        self.assertEqual(self.send_due(march - timedelta(minutes=1)), 0)
        self.assertEqual(self.send_due(march), 1)
        self.assertEqual(self.send_due(october - timedelta(minutes=1)), 0)
        self.assertEqual(self.send_due(october), 1)

    def test_turned_off_or_cancelled(self):
        EducatorSettings.objects.create(educator=self.samia, remind_residents=False)
        self.meeting(at(MONDAY, 10))
        cancelled = self.meeting(at(MONDAY, 11), educator=self.julien, status="cancelled")
        self.assertEqual(self.send_due(at(SUNDAY, 18)), 0)
        # Cancelled after the claim: the task sends nothing.
        with mock.patch("django.utils.timezone.now", return_value=at(SUNDAY, 18)):
            remind_task.call(meeting_id=cancelled.pk, kind="day_before")
        self.push.assert_not_called()

    def test_a_queue_failure_gives_the_claim_back(self):
        meeting = self.meeting(at(MONDAY, 10))
        broken = mock.Mock()
        broken.enqueue.side_effect = RuntimeError("database is locked")
        with (
            mock.patch("appointments.tasks.remind_task", broken),
            self.assertLogs("appointments.reminders", "ERROR"),
        ):
            self.assertEqual(self.send_due(at(SUNDAY, 18)), 0)
        meeting.refresh_from_db()
        self.assertIsNone(meeting.day_before_sent_at)
        self.assertEqual(self.send_due(at(SUNDAY, 18, 1)), 1)  # the next minute

    def test_run_scheduled_sends_them_even_after_another_failure(self):
        now = timezone.now()
        self.meeting(now + timedelta(minutes=50))  # due for the hour-before reminder
        out, err = StringIO(), StringIO()
        with (
            mock.patch(
                "messaging.management.commands.run_scheduled.run_due",
                side_effect=RuntimeError("boom"),
            ),
            self.assertLogs("messaging.management.commands.run_scheduled", "ERROR"),
        ):
            call_command("run_scheduled", stdout=out, stderr=err)
        self.assertIn("Rappels de rendez-vous : 1.", out.getvalue())
        self.assertIn("Échec : messages", err.getvalue())
        self.push.assert_called_once()


class CancelTests(ReminderTestCase):
    def test_resident_cancels_and_the_slot_is_free_again(self):
        availability.save_grid(self.samia, ["0-1000", "0-1030", "0-1100"])
        now = at(MONDAY - timedelta(days=3), 9)
        meeting = booking.book(self.ines, at(MONDAY, 10), [self.samia], now=now)
        booking.book(self.ines, at(MONDAY, 11), [self.samia], now=now)
        # Two meetings to come: the limit.
        with self.assertRaisesMessage(booking.BookingRefused, "le prochain soit passé"):
            booking.book(self.ines, at(MONDAY, 10, 30), [self.samia], now=now)
        with self.captureOnCommitCallbacks(execute=True):
            booking.cancel(meeting, self.ines, now)
        meeting.refresh_from_db()
        self.assertEqual((meeting.status, meeting.cancelled_by), ("cancelled", self.ines))
        self.assertEqual(self.push.call_args.args[0], self.samia)
        self.assertEqual(
            self.push.call_args.kwargs["body"],
            "Inès a annulé le rendez-vous du lundi 16 novembre à 10:00.",
        )
        self.sms.assert_not_called()  # a resident cancelling costs no SMS
        # The slot is free again, and the limit too.
        booking.book(self.ines, at(MONDAY, 10, 30), [self.samia], now=now)
        booking.book(self.yanis, at(MONDAY, 10), [self.samia], now=now)
        # A second click by Inès: already done, by her.
        with self.assertRaises(booking.AlreadyCancelled):
            booking.cancel(meeting, self.ines, now)

    def test_educator_cancels_with_sms_fallback(self):
        self.push.return_value = SendResult(sent=0)
        meeting = self.meeting(at(MONDAY, 10))
        with self.captureOnCommitCallbacks(execute=True):
            booking.cancel(meeting, self.samia, at(MONDAY, 8))
        self.assertEqual(self.push.call_args.args[0], self.ines)
        self.assertIn(
            "Samia a annulé votre rendez-vous du lundi 16 novembre à 10:00.",
            self.sms.call_args.args[1],
        )

    def test_both_cancel(self):
        meeting = self.meeting(at(MONDAY, 10))
        booking.cancel(meeting, self.samia, at(MONDAY, 8))
        with self.assertRaisesMessage(booking.CancelRefused, "déjà annulé") as refused:
            booking.cancel(meeting, self.ines, at(MONDAY, 8))
        self.assertNotIsInstance(refused.exception, booking.AlreadyCancelled)

    def test_refused(self):
        meeting = self.meeting(at(MONDAY, 10))
        with self.assertRaisesMessage(booking.CancelRefused, "déjà commencé"):
            booking.cancel(meeting, self.ines, at(MONDAY, 10, 5))
        with self.assertRaisesMessage(booking.CancelRefused, "pas le vôtre"):
            booking.cancel(meeting, self.yanis, at(MONDAY, 8))
        self.assertEqual(Appointment.objects.get().status, "confirmed")

    def test_departure_tells_nobody(self):
        meeting = self.meeting(timezone.now() + timedelta(days=2))
        booking.cancel_on_departure(None, resident=self.ines)
        meeting.refresh_from_db()
        self.assertEqual((meeting.status, meeting.cancelled_by), ("cancelled", None))
        from ..tasks import cancel_notice_task

        cancel_notice_task.call(meeting_id=meeting.pk)
        self.push.assert_not_called()


class CancelPageTests(ReminderTestCase):
    def test_resident_page(self):
        meeting = self.meeting(timezone.now() + timedelta(days=2))
        log_in_verified(self.client, self.ines)
        detail = reverse("rdv:detail", args=[meeting.pk])
        response = self.client.get(detail)
        save_page("appointments-detail-cancel", response)
        self.assertContains(response, "Annuler ce rendez-vous")
        self.assertContains(response, "Un rappel vous est envoyé la veille au soir et une heure")
        self.assertContains(response, "Nous prévenons Samia.")
        cancel = reverse("rdv:cancel", args=[meeting.pk])
        self.assertEqual(self.client.get(cancel).status_code, 405)
        response = self.client.post(cancel, follow=True)
        save_page("appointments-detail-cancelled", response)
        self.assertContains(response, "Rendez-vous annulé. Nous prévenons Samia.")
        self.assertContains(response, "Annulé par vous")
        self.assertNotContains(response, "Oui, annuler")
        self.assertNotContains(response, "Un rappel")
        # A second click: no warning on top of the success.
        response = self.client.post(cancel, follow=True)
        self.assertNotContains(response, "déjà annulé")
        log_in_verified(self.client, self.yanis)
        self.assertEqual(self.client.post(cancel).status_code, 404)

    def test_csrf_is_required(self):
        meeting = self.meeting(timezone.now() + timedelta(days=2))
        client = Client(enforce_csrf_checks=True)
        log_in_verified(client, self.ines)
        self.assertEqual(client.post(reverse("rdv:cancel", args=[meeting.pk])).status_code, 403)
        meeting.refresh_from_db()
        self.assertEqual(meeting.status, "confirmed")

    def test_reminder_sentence_says_what_will_come(self):
        now = timezone.now()
        log_in_verified(self.client, self.ines)
        # Booked just now for in 3 hours: only the hour before.
        soon = self.meeting(now + timedelta(hours=3), created=now)
        response = self.client.get(reverse("rdv:detail", args=[soon.pk]))
        self.assertContains(response, "Un rappel vous est envoyé une heure avant.")
        # Reminders turned off: no promise.
        EducatorSettings.objects.create(educator=self.samia, remind_residents=False)
        response = self.client.get(reverse("rdv:detail", args=[soon.pk]))
        self.assertNotContains(response, "Un rappel")

    def test_educator_page(self):
        meeting = self.meeting(timezone.now() + timedelta(days=2))
        cancel = reverse("appointments:cancel_meeting", args=[meeting.pk])
        log_in_verified(self.client, self.julien)
        self.assertEqual(self.client.post(cancel).status_code, 404)  # not their meeting
        log_in_verified(self.client, self.samia)
        response = self.client.get(reverse("appointments:availability"))
        self.assertContains(response, "Oui, annuler et prévenir la personne")
        response = self.client.post(cancel, follow=True)
        self.assertContains(response, "Rendez-vous annulé. La personne est prévenue.")
        response = self.client.post(cancel, follow=True)  # a second click
        self.assertNotContains(response, "déjà annulé")
        log_in_verified(self.client, self.ines)
        response = self.client.get(reverse("rdv:detail", args=[meeting.pk]))
        self.assertContains(response, "Annulé par Samia")

    def test_educator_sees_started_and_cancelled_meetings(self):
        now = timezone.now()
        self.meeting(now - timedelta(minutes=5), end=now + timedelta(minutes=25))
        gone = self.meeting(now + timedelta(days=2), resident=self.yanis)
        booking.cancel(gone, self.yanis)
        log_in_verified(self.client, self.samia)
        response = self.client.get(reverse("appointments:availability"))
        save_page("appointments-availability-cancelled", response)
        self.assertContains(response, "En cours")
        self.assertNotContains(response, "Oui, annuler")  # not once it has started
        self.assertContains(response, "Annulés")
        self.assertContains(response, "annulé par la personne")

    def test_the_reminder_setting_survives_a_save(self):
        url = reverse("appointments:availability")
        log_in_verified(self.client, self.samia)
        response = self.client.get(url)
        self.assertContains(response, 'name="remind_residents"')
        data = {"cell": ["0-1000"], "slot_minutes": "30", "notice": "2h"}
        self.client.post(url, {**data, "remind_residents": "on"})
        self.assertTrue(EducatorSettings.objects.get(educator=self.samia).remind_residents)
        self.client.post(url, data)  # unticked
        self.assertFalse(EducatorSettings.objects.get(educator=self.samia).remind_residents)
