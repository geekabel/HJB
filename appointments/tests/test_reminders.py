"""Reminders and cancellation of the meetings (card T29)."""

from datetime import date, datetime, time, timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user
from push.services import SendResult
from tools.html_capture import save_page

from .. import availability, booking, reminders
from ..models import Appointment, EducatorSettings

MONDAY = date(2026, 11, 16)


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
        self._patch("messaging.sending.sms_ready", True)

    def _patch(self, target, value):
        patcher = mock.patch(target, return_value=value)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def meeting(self, start, **kwargs):
        data = {"educator": self.samia, "resident": self.ines, "start": start}
        data.update(kwargs)
        data.setdefault("end", data["start"] + timedelta(minutes=30))
        return Appointment.objects.create(**data)


class ReminderTests(ReminderTestCase):
    def test_the_day_before_at_six_pm_once(self):
        meeting = self.meeting(at(MONDAY, 10))
        sunday = MONDAY - timedelta(days=1)
        self.assertEqual(reminders.send_due(at(sunday, 17, 59)), 0)
        self.assertEqual(reminders.send_due(at(sunday, 18, 0)), 1)
        self.assertEqual(reminders.send_due(at(sunday, 18, 1)), 0)  # never twice
        user, kwargs = self.push.call_args.args[0], self.push.call_args.kwargs
        self.assertEqual(user, self.ines)
        self.assertEqual(kwargs["title"], "Rappel de rendez-vous")
        self.assertEqual(
            kwargs["body"], "Rendez-vous demain, lundi 16 novembre à 10:00, avec Samia."
        )
        self.assertEqual(kwargs["url"], reverse("rdv:detail", args=[meeting.pk]))
        self.sms.assert_not_called()  # the notification arrived

    def test_sms_only_without_a_device_and_only_the_day_before(self):
        self.push.return_value = SendResult(sent=0)
        self.meeting(at(MONDAY, 10))
        reminders.send_due(at(MONDAY - timedelta(days=1), 18))
        self.assertEqual(
            self.sms.call_args.args,
            (
                "+33611111111",
                "HJB : rappel, rendez-vous demain lundi 16 novembre à 10:00 avec Samia.",
            ),
        )
        self.sms.reset_mock()
        self.assertEqual(reminders.send_due(at(MONDAY, 9)), 1)  # one hour before
        self.assertEqual(self.push.call_args.kwargs["title"], "Rendez-vous dans une heure")
        self.sms.assert_not_called()  # no SMS for the hour-before reminder

    def test_never_late(self):
        self.meeting(at(MONDAY, 10))
        # The worker stopped all evening: at 8:30 the day-before reminder is useless.
        self.assertEqual(reminders.send_due(at(MONDAY, 8, 30)), 0)
        # After the start: nothing at all.
        self.assertEqual(reminders.send_due(at(MONDAY, 10, 1)), 0)
        self.push.assert_not_called()

    def test_turned_off_or_cancelled(self):
        EducatorSettings.objects.create(educator=self.samia, remind_residents=False)
        self.meeting(at(MONDAY, 10))
        cancelled = self.meeting(at(MONDAY, 11), educator=self.julien, status="cancelled")
        self.assertEqual(reminders.send_due(at(MONDAY - timedelta(days=1), 18)), 0)
        # Cancelled after the claim: the task sends nothing.
        from ..tasks import remind_task

        remind_task.call(meeting_id=cancelled.pk, kind="day_before")
        self.push.assert_not_called()

    def test_run_scheduled_sends_them(self):
        with mock.patch("appointments.reminders.send_due", return_value=2) as send:
            call_command("run_scheduled", stdout=StringIO())
        send.assert_called_once()


class CancelTests(ReminderTestCase):
    def test_resident_cancels_and_the_slot_is_free_again(self):
        availability.save_grid(self.samia, ["0-1000"])
        now = at(MONDAY - timedelta(days=3), 9)
        meeting = booking.book(self.ines, at(MONDAY, 10), [self.samia], now=now)
        with self.captureOnCommitCallbacks(execute=True):
            booking.cancel(meeting, self.ines, now)
        meeting.refresh_from_db()
        self.assertEqual((meeting.status, meeting.cancelled_by), ("cancelled", self.ines))
        self.assertEqual(self.push.call_args.args[0], self.samia)
        self.assertEqual(
            self.push.call_args.kwargs["body"],
            "Inès a annulé le rendez-vous du lundi 16 novembre à 10:00.",
        )
        # The slot is free again: Yanis books it.
        booking.book(self.yanis, at(MONDAY, 10), [self.samia], now=now)
        with self.assertRaisesMessage(booking.CancelRefused, "déjà annulé"):
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

    def test_refused(self):
        meeting = self.meeting(at(MONDAY, 10))
        with self.assertRaisesMessage(booking.CancelRefused, "déjà commencé"):
            booking.cancel(meeting, self.ines, at(MONDAY, 10, 5))
        with self.assertRaisesMessage(booking.CancelRefused, "pas le vôtre"):
            booking.cancel(meeting, self.yanis, at(MONDAY, 8))
        self.assertEqual(Appointment.objects.get().status, "confirmed")


class CancelPageTests(ReminderTestCase):
    def test_resident_page(self):
        meeting = self.meeting(timezone.now() + timedelta(days=2))
        log_in_verified(self.client, self.ines)
        detail = reverse("rdv:detail", args=[meeting.pk])
        response = self.client.get(detail)
        save_page("appointments-detail-cancel", response)
        self.assertContains(response, "Annuler ce rendez-vous")
        self.assertContains(response, "Un rappel vous est envoyé la veille au soir")
        response = self.client.post(reverse("rdv:cancel", args=[meeting.pk]), follow=True)
        save_page("appointments-detail-cancelled", response)
        self.assertContains(response, "Rendez-vous annulé. L&#x27;éducateur est prévenu.")
        self.assertContains(response, "Annulé par vous")
        self.assertNotContains(response, "Oui, annuler")
        log_in_verified(self.client, self.yanis)
        self.assertEqual(
            self.client.post(reverse("rdv:cancel", args=[meeting.pk])).status_code, 404
        )

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
        log_in_verified(self.client, self.ines)
        response = self.client.get(reverse("rdv:detail", args=[meeting.pk]))
        self.assertContains(response, "Annulé par Samia")
