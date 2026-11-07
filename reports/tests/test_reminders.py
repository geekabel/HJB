"""Delays of the reports: late alerts and the morning summary (card T32)."""

from datetime import datetime, time, timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user

from .. import handling, reminders
from ..models import DailySummary, Report
from .test_reports import NEW, ReportTestCase


def at(day, hour, minute=0):
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


class ReminderTests(ReportTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.marc = make_user("marc", Role.MAINTENANCE, first_name="Marc")
        cls.samia = make_user("samia", Role.EDUCATOR, first_name="Samia")

    def setUp(self):
        super().setUp()
        patcher = mock.patch("reports.tasks.push")
        self.push = patcher.start()
        self.addCleanup(patcher.stop)
        mock.patch("reports.tasks.reach").start()
        self.addCleanup(mock.patch.stopall)

    def report(self, **changes):
        log_in_verified(self.client, self.ines)
        self.client.post(NEW, self.data(**changes))
        return Report.objects.latest("pk")

    def late_only(self, now):
        """send_due without the morning summary: these tests run at any hour."""
        with mock.patch("reports.reminders._summary", return_value=False):
            return reminders.send_due(now)

    def told(self):
        return {call.args[0] for call in self.push.call_args_list}

    def test_late_report_told_once_to_everyone_who_handles_reports(self):
        report = self.report(urgency="urgent")
        before = report.due_at - timedelta(minutes=1)
        self.assertEqual(self.late_only(before), 0)
        after = report.due_at + timedelta(minutes=1)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.late_only(after), 1)
        self.assertEqual(self.told(), {self.karim, self.marc})  # not the educator
        kwargs = self.push.call_args.kwargs
        self.assertEqual(kwargs["title"], "Signalement en retard")
        self.assertEqual(kwargs["body"], "Chambre 312, électricité (urgent).")
        self.assertNotIn("lampe", kwargs["body"])  # never the description
        self.assertEqual(self.late_only(after + timedelta(minutes=5)), 0)

    def test_late_report_told_to_the_person_in_charge(self):
        report = self.report(urgency="urgent")
        handling.take(report, self.karim, self.marc)
        with self.captureOnCommitCallbacks(execute=True):
            self.late_only(report.due_at + timedelta(minutes=1))
        self.assertEqual(self.told(), {self.marc})

    def test_planned_or_done_is_not_late(self):
        report = self.report(urgency="urgent")
        start = timezone.now() + timedelta(days=1)
        handling.plan(report, self.marc, start, start + timedelta(hours=1))
        self.assertEqual(self.late_only(report.due_at + timedelta(minutes=1)), 0)

    def at_clock(self, moment):
        """The clock of the task (it checks the time again) at ``moment``."""
        return mock.patch("django.utils.timezone.now", return_value=moment)

    def test_morning_summary(self):
        today = timezone.localdate()
        while today.weekday() >= 5:  # a weekday
            today += timedelta(days=1)
        fresh = self.report(urgency="urgent")
        late = self.report()
        Report.objects.filter(pk=fresh.pk).update(due_at=at(today, 18))
        Report.objects.filter(pk=late.pk).update(due_at=at(today, 8))
        with self.at_clock(at(today, 8, 59)):
            reminders.send_due(at(today, 8, 59))
        self.assertFalse(DailySummary.objects.exists())
        with self.at_clock(at(today, 9, 0)):
            reminders.send_due(at(today, 9, 0))
        self.assertEqual(self.told(), {self.karim, self.marc})
        summary = [
            c for c in self.push.call_args_list if c.kwargs["title"] == "Signalements du jour"
        ]
        # The late new report counts once, as late.
        self.assertEqual(summary[-1].kwargs["body"], "1 nouveau · 1 en retard.")
        self.assertEqual(summary[-1].kwargs["url"], reverse("reports_staff:board"))
        # Once a day, and never after noon.
        self.push.reset_mock()
        with self.at_clock(at(today, 9, 1)):
            reminders.send_due(at(today, 9, 1))
        self.assertFalse(
            [c for c in self.push.call_args_list if c.kwargs["title"] == "Signalements du jour"]
        )
        tomorrow = today + timedelta(days=1)
        with self.at_clock(at(tomorrow, 12, 0)):
            reminders.send_due(at(tomorrow, 12, 0))
        self.assertFalse(DailySummary.objects.filter(day=tomorrow).exists())

    def test_stale_summary_not_sent(self):
        """Claimed at 9:00, but the worker runs the task at 13:00: too late."""
        from ..tasks import daily_summary_task

        today = timezone.localdate()
        self.report()
        with self.at_clock(at(today, 13, 0)):
            daily_summary_task.call(day=today.isoformat())
        with self.at_clock(at(today + timedelta(days=1), 9, 30)):
            daily_summary_task.call(day=today.isoformat())
        self.push.assert_not_called()

    def test_no_summary_on_the_weekend(self):
        self.report()
        saturday = timezone.localdate()
        while saturday.weekday() != 5:
            saturday += timedelta(days=1)
        for day in (saturday, saturday + timedelta(days=1)):
            with self.at_clock(at(day, 9, 30)):
                reminders.send_due(at(day, 9, 30))
        self.assertFalse(DailySummary.objects.exists())
        monday = saturday + timedelta(days=2)
        with self.at_clock(at(monday, 9, 30)):
            reminders.send_due(at(monday, 9, 30))
        self.assertTrue(DailySummary.objects.filter(day=monday).exists())

    def test_nothing_to_say(self):
        today = timezone.localdate()
        while today.weekday() >= 5:
            today += timedelta(days=1)
        with self.at_clock(at(today, 9, 30)):
            reminders.send_due(at(today, 9, 30))
        self.push.assert_not_called()
        self.assertTrue(DailySummary.objects.filter(day=today).exists())

    def test_run_scheduled_runs_it(self):
        report = self.report(urgency="urgent")
        Report.objects.filter(pk=report.pk).update(due_at=timezone.now() - timedelta(minutes=1))
        out = StringIO()
        call_command("run_scheduled", stdout=out)
        self.assertIn("Signalements : ", out.getvalue())
        report.refresh_from_db()
        self.assertIsNotNone(report.late_alerted_at)

    def test_delay_text(self):
        report = self.report()  # 48 h
        self.assertEqual(report.delay_text(report.created_at), "reste 2 j")
        self.assertEqual(report.delay_text(report.due_at - timedelta(hours=20)), "reste 20 h")
        self.assertEqual(report.delay_text(report.due_at + timedelta(hours=5)), "retard 5 h")
        self.assertEqual(report.delay_text(report.due_at + timedelta(minutes=25)), "retard 25 min")
        self.assertEqual(report.delay_text(report.due_at - timedelta(minutes=40)), "reste 40 min")
        self.assertEqual(report.delay_text(report.due_at), "retard 1 min")
        log_in_verified(self.client, self.marc)
        Report.objects.filter(pk=report.pk).update(due_at=timezone.now() - timedelta(hours=26))
        response = self.client.get(reverse("reports_staff:board"))
        self.assertContains(response, "Gênant · retard 26 h")
