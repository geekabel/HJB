"""The staff handle the reports (card T31)."""

from datetime import timedelta
from unittest import mock

from django.urls import reverse
from django.utils import timezone

from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user
from tools.html_capture import save_page

from ..models import Report, ReportEvent
from .test_reports import NEW, ReportTestCase, jpeg

BOARD = reverse("reports_staff:board")


class BoardTestCase(ReportTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.marc = make_user("marc", Role.MAINTENANCE, first_name="Marc")
        cls.samia = make_user("samia", Role.EDUCATOR, first_name="Samia")

    def setUp(self):
        super().setUp()
        patcher = mock.patch("reports.tasks.reach")
        self.reach = patcher.start()
        self.addCleanup(patcher.stop)

    def report(self, **changes):
        log_in_verified(self.client, self.ines)
        self.client.post(NEW, self.data(**changes))
        return Report.objects.latest("pk")

    def url(self, name, report):
        return reverse(f"reports_staff:{name}", args=[report.pk])


class BoardTests(BoardTestCase):
    def test_board_and_filters(self):
        fresh = self.report(photos=[jpeg(exif=False)])
        late = self.report(urgency="urgent", description="Prise qui chauffe")
        Report.objects.filter(pk=late.pk).update(due_at=timezone.now() - timedelta(hours=1))
        log_in_verified(self.client, self.marc)
        self.assertRedirects(self.client.get(reverse("home")), BOARD)
        response = self.client.get(BOARD)
        save_page("reports-board", response)
        page = response.content.decode()
        # Late first in its column, with the yellow badge.
        self.assertLess(page.index("Prise qui chauffe"), page.index("La lampe"))
        self.assertContains(response, "Urgent · en retard")
        self.assertContains(response, "1 photo")
        self.assertContains(response, "En retard (1)")
        self.assertContains(response, '<span class="visually-hidden">2 nouveaux</span>')
        response = self.client.get(BOARD, {"show": "late"})
        self.assertNotContains(response, "La lampe")
        response = self.client.get(BOARD, {"show": "mine"})
        self.assertNotContains(response, "Prise qui chauffe")
        self.client.post(self.url("take", fresh), {"from": "board"})
        response = self.client.get(BOARD, {"show": "mine"})
        self.assertContains(response, "La lampe")

    def test_who_sees_the_board(self):
        report = self.report(photos=[jpeg(exif=False)])
        photo = reverse("reports_staff:photo", args=[report.photos.get().pk])
        log_in_verified(self.client, self.samia)  # educator: not for her
        self.assertEqual(self.client.get(BOARD).status_code, 403)
        self.assertEqual(self.client.get(photo).status_code, 403)
        self.assertNotContains(self.client.get(reverse("appointments:availability")), BOARD)
        log_in_verified(self.client, self.karim)  # front desk
        self.assertEqual(self.client.get(BOARD).status_code, 200)
        response = self.client.get(photo)
        self.assertEqual(response["Content-Type"], "image/jpeg")
        self.assertIn("no-store", response["Cache-Control"])


class StepTests(BoardTestCase):
    def test_take_plan_done(self):
        report = self.report(access="no")
        log_in_verified(self.client, self.marc)
        response = self.client.get(self.url("detail", report))
        save_page("reports-staff-detail-new", response)
        self.assertContains(response, "Je m'en occupe")

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self.url("take", report))
        report.refresh_from_db()
        self.assertEqual((report.status, report.assigned_to), ("acknowledged", self.marc))
        self.assertEqual(self.reach.call_args.kwargs["body"], "Il est pris en charge.")
        # A second "Je m'en occupe" (from another tab) is refused.
        response = self.client.post(self.url("take", report), follow=True)
        self.assertContains(response, "déjà pris en charge")

        day = timezone.localdate() + timedelta(days=1)
        bad = {"plan-day": day.isoformat(), "plan-start": "10:00", "plan-end": "09:00"}
        response = self.client.post(self.url("plan", report), bad)
        self.assertContains(
            response, "L&#x27;heure de fin doit être après le début.", status_code=400
        )
        past = bad | {"plan-day": (day - timedelta(days=3)).isoformat(), "plan-end": "11:00"}
        response = self.client.post(self.url("plan", report), past)
        self.assertContains(response, "un jour à venir", status_code=400)
        good = {
            "plan-day": day.isoformat(),
            "plan-start": "10:00",
            "plan-end": "12:00",
            "plan-note": "Libérez l'accès.",
        }
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self.url("plan", report), good)
        report.refresh_from_db()
        self.assertEqual(report.status, "scheduled")
        self.assertEqual(timezone.localtime(report.intervention_start).hour, 10)
        kwargs = self.reach.call_args.kwargs
        self.assertIn("de 10:00 à 12:00", kwargs["body"])
        self.assertIn("Soyez présent", kwargs["sms"])  # she wants to be there
        response = self.client.get(self.url("detail", report))
        save_page("reports-staff-detail-scheduled", response)
        self.assertContains(response, "Libérez l&#x27;accès.")

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                self.url("done", report), {"done-note": "Ampoule et douille changées."}
            )
        report.refresh_from_db()
        self.assertEqual(report.status, "done")
        self.assertIn("Dites-nous si c'est réglé", self.reach.call_args.kwargs["body"])
        self.assertEqual(
            list(report.events.values_list("type", flat=True)),
            ["created", "acknowledged", "scheduled", "intervention"],
        )
        response = self.client.post(self.url("done", report), follow=True)
        self.assertContains(response, "déjà marqué comme fait")

    def test_resident_sees_the_planned_visit(self):
        report = self.report(access="yes")
        log_in_verified(self.client, self.marc)
        day = timezone.localdate() + timedelta(days=2)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                self.url("plan", report),
                {"plan-day": day.isoformat(), "plan-start": "14:00", "plan-end": "15:00"},
            )
        self.assertEqual(self.reach.call_args.kwargs["sms"], "")  # she lets them in
        log_in_verified(self.client, self.ines)
        response = self.client.get(reverse("reports:detail", args=[report.pk]))
        save_page("reports-detail-scheduled", response)
        self.assertContains(response, "Intervention prévue")
        self.assertContains(response, "de 14:00 à 15:00")

    def test_assign(self):
        report = self.report()
        log_in_verified(self.client, self.karim)
        self.client.post(self.url("assign", report), {"assignee": self.marc.pk})
        report.refresh_from_db()
        self.assertEqual((report.status, report.assigned_to), ("acknowledged", self.marc))
        # Only someone who handles reports.
        self.client.post(self.url("assign", report), {"assignee": self.samia.pk})
        report.refresh_from_db()
        self.assertEqual(report.assigned_to, self.marc)
        self.assertEqual(ReportEvent.objects.filter(report=report, type="acknowledged").count(), 1)
