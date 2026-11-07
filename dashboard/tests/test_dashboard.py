"""Staff dashboard (card T35)."""

from datetime import date, timedelta

from django.urls import reverse
from django.utils import timezone

from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user
from housing.models import Floor, Room, Stay
from messaging.models import AttendanceReply, Campaign, MessageType, ReplyType
from messaging.tests.test_inbox import InboxTestCase
from reports.models import Report
from tools.html_capture import save_page

from .. import services

HOME = reverse("dashboard:home")


class DashboardTests(InboxTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.marie = make_user("marie", Role.ADMIN, first_name="Marie")
        cls.f4 = Floor.objects.create(number=4, visit_order=3)
        lea = make_user("lea", first_name="Léa")
        Stay.objects.create(
            resident=lea,
            room=Room.objects.create(number="401", floor=cls.f4),
            arrival=date(2026, 9, 1),
        )
        cls.f1 = Floor.objects.create(number=1, visit_order=1)
        Floor.objects.filter(pk=cls.f3.pk).update(visit_order=2)

    def report(self, **changes):
        data = {
            "resident": self.ines,
            "room": self.room,
            "category": "heating",
            "description": "Radiateur froid",
            "urgency": "urgent",
            "due_at": timezone.now() - timedelta(hours=3),
        }
        return Report.objects.create(**(data | changes))

    def test_dashboard_for_the_front_desk(self):
        late = self.report()
        self.report(due_at=timezone.now() + timedelta(days=2))
        soon = timezone.localdate() + timedelta(days=1)
        visit = self.send(
            "Visite 3e étage",
            type=MessageType.VISIT,
            floors=[self.f3],
            reply_type=ReplyType.ATTENDANCE,
            event_date=soon,
        )
        AttendanceReply.objects.create(campaign=visit, resident=self.ines, answer="present")
        Campaign.objects.create(
            title="Rappel visite",
            body="B",
            author=self.nadia,
            everyone=True,
            status=Campaign.Status.SCHEDULED,
            send_at=timezone.now() + timedelta(days=1),
        )
        log_in_verified(self.client, self.nadia)
        self.assertRedirects(self.client.get(reverse("home")), HOME)
        response = self.client.get(HOME)
        save_page("dashboard", response)
        page = response.content.decode()
        self.assertIn('aria-current="page">Tableau de bord', page)
        self.assertIn("Signalements ouverts", page)
        self.assertIn("dont 1 en retard", page)
        self.assertIn(reverse("reports_staff:detail", args=[late.pk]), page)
        self.assertIn("1 réponse sur 2 · 1 présent · 0 absent", page)
        self.assertIn("Rappel visite", page)
        self.assertIn("Tous les résidents", page)
        # Rotation: 1er, 3e (visited), 4e: the next one is the 4th floor.
        self.assertIn(f"?etage={self.f4.pk}", page)
        self.assertIn("Préparer la visite : 4e étage", page)

    def test_rotation_order(self):
        steps = services.rotation()
        self.assertEqual([s.floor for s in steps], [self.f1, self.f3, self.f4])
        self.assertTrue(steps[0].is_next)  # never visited: the first one
        self.send("Visite 4e", type=MessageType.VISIT, floors=[self.f4])
        steps = services.rotation()
        self.assertTrue(steps[2].is_last)
        self.assertTrue(steps[0].is_next)  # after the last floor: back to the first

    def test_next_visit_prefilled(self):
        log_in_verified(self.client, self.nadia)
        response = self.client.get(reverse("messaging:new"), {"etage": self.f4.pk})
        form = response.context["form"]
        self.assertEqual(form.instance.type, MessageType.VISIT)
        self.assertEqual(form.initial["floors"], [self.f4.pk])
        self.assertEqual(self.client.get(reverse("messaging:new"), {"etage": "x"}).status_code, 200)

    def test_who_sees_what(self):
        log_in_verified(self.client, self.ines)  # a resident never
        self.assertIn(self.client.get(HOME).status_code, (302, 403))
        samia = make_user("samia", Role.EDUCATOR)
        log_in_verified(self.client, samia)  # an educator: no reports part
        response = self.client.get(HOME)
        self.assertNotContains(response, "Signalements ouverts")
        self.assertContains(response, "Envois programmés")
        self.report()
        log_in_verified(self.client, self.marie)
        response = self.client.get(HOME)
        self.assertContains(response, "Wifi à renouveler")
        self.assertContains(response, "Rendez-vous aujourd&#x27;hui")

    def test_meetings_today_counted_by_educator(self):
        from appointments.models import Appointment

        samia = make_user("samia", Role.EDUCATOR, first_name="Samia")
        start = timezone.localtime().replace(hour=23, minute=0, second=0, microsecond=0)
        Appointment.objects.create(
            educator=samia, resident=self.ines, start=start, end=start + timedelta(minutes=30)
        )
        figures = {f.label: f for f in services.figures(self.nadia, timezone.now())}
        self.assertEqual(figures["Rendez-vous aujourd'hui"].value, 1)
        self.assertEqual(figures["Rendez-vous aujourd'hui"].detail, "Samia 1")
