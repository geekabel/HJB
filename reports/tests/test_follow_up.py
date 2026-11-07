"""The resident follows his report and confirms it is fixed (card T33)."""

from datetime import timedelta
from unittest import mock

from django.urls import reverse
from django.utils import timezone

from accounts.tests.helpers import log_in_verified
from tools.html_capture import save_page

from .. import handling, reminders
from ..models import Report, ReportEvent
from .test_board import BoardTestCase


class FollowUpTests(BoardTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch("reports.tasks.push")
        self.push = patcher.start()
        self.addCleanup(patcher.stop)

    def done_report(self):
        report = self.report()
        handling.take(report, self.karim, self.marc)
        handling.done(report, self.marc, "Ampoule changée.")
        report.refresh_from_db()
        return report

    def page(self, report):
        log_in_verified(self.client, self.ines)
        return self.client.get(reverse("reports:detail", args=[report.pk]))

    def post(self, name, report, data=None):
        log_in_verified(self.client, self.ines)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(
                reverse(f"reports:{name}", args=[report.pk]), data or {}, follow=True
            )

    def test_question_and_history(self):
        report = self.done_report()
        response = self.page(report)
        save_page("reports-detail-done", response)
        page = response.content.decode()
        self.assertIn("Le problème est-il réglé ?", page)
        self.assertIn("Ampoule changée.", page)
        self.assertIn("Pris en charge par Karim", page)  # who took it
        self.assertNotIn("Confié", page)  # staff only
        self.assertLess(
            page.index('what">Intervention faite'), page.index('what">Signalement envoyé')
        )
        self.assertIn("sera clos le", page)
        self.assertNotIn("Rien ne bouge ?", page)  # nothing to remind once done

    def test_confirm(self):
        report = self.done_report()
        response = self.post("confirm", report)
        self.assertContains(response, "Merci ! Le signalement est clos.")
        report.refresh_from_db()
        self.assertEqual(report.status, Report.Status.CLOSED)
        self.assertEqual(report.events.latest("pk").type, ReportEvent.Type.CONFIRMED)
        response = self.post("confirm", report)
        self.assertContains(response, "n&#x27;attend pas votre réponse")
        response = self.client.get(reverse("reports:list"))
        self.assertContains(response, "Terminés")

    def test_reopen(self):
        report = self.done_report()
        old_due = report.due_at
        Report.objects.filter(pk=report.pk).update(late_alerted_at=timezone.now())
        before = timezone.now()
        response = self.post("reopen", report, {"note": "La lampe clignote encore."})
        self.assertContains(response, "l&#x27;équipe est prévenue")
        report.refresh_from_db()
        self.assertEqual(report.status, Report.Status.ACKNOWLEDGED)
        self.assertIsNone(report.late_alerted_at)  # can be late again (T32)
        self.assertIsNone(report.done_at)
        self.assertGreater(report.due_at, old_due)
        self.assertLess(abs(report.due_at - (before + timedelta(hours=48))), timedelta(minutes=1))
        event = report.events.latest("pk")
        self.assertEqual((event.type, event.note), ("reopened", "La lampe clignote encore."))
        self.assertEqual(self.push.call_args.args[0], self.marc)  # the person in charge
        self.assertEqual(self.push.call_args.kwargs["title"], "Pas encore réglé")
        self.assertNotIn("clignote", self.push.call_args.kwargs["body"])

    def test_remind_after_48_hours(self):
        report = self.report()
        response = self.page(report)
        self.assertContains(response, "Vous pourrez relancer l'équipe à partir du")
        response = self.post("remind", report)
        self.assertContains(response, "un peu plus tard")
        report.events.update(created_at=timezone.now() - timedelta(hours=49))
        response = self.page(report)
        self.assertContains(response, "Relancer l'équipe")
        response = self.post("remind", report)
        self.assertContains(response, "L&#x27;équipe est relancée.")
        self.assertEqual(report.events.latest("pk").type, ReportEvent.Type.REMINDER)
        self.assertEqual(self.push.call_args.kwargs["title"], "Relance du résident")
        self.assertEqual({c.args[0] for c in self.push.call_args_list}, {self.karim, self.marc})
        response = self.post("remind", report)  # once per 48 h
        self.assertContains(response, "un peu plus tard")

    def test_closed_after_3_days_without_answer(self):
        report = self.done_report()
        with mock.patch("reports.reminders._summary", return_value=False):
            self.assertEqual(reminders.send_due(report.done_at + timedelta(days=2)), 0)
            self.assertEqual(reminders.send_due(report.done_at + timedelta(days=3)), 1)
        report.refresh_from_db()
        self.assertEqual(report.status, Report.Status.CLOSED)
        event = report.events.latest("pk")
        self.assertEqual((event.type, event.author), ("closed", None))

    def test_only_my_reports(self):
        report = self.done_report()
        log_in_verified(self.client, self.yanis)
        for name in ("confirm", "reopen", "remind"):
            response = self.client.post(reverse(f"reports:{name}", args=[report.pk]))
            self.assertEqual(response.status_code, 404)
        report.refresh_from_db()
        self.assertEqual(report.status, Report.Status.DONE)

    def test_board_shows_the_closing_day(self):
        self.done_report()
        log_in_verified(self.client, self.marc)
        response = self.client.get(reverse("reports_staff:board"))
        self.assertContains(response, "sans réponse")
