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
        Stay.objects.create(
            resident=make_user("noe", first_name="Noé"),
            room=Room.objects.create(number="101", floor=cls.f1),
            arrival=date(2026, 9, 1),
        )
        # A floor with offices only: never in the rotation.
        cls.f0 = Floor.objects.create(number=0, visit_order=0)
        Room.objects.create(number="001", floor=cls.f0)
        Floor.objects.filter(pk=cls.f3.pk).update(visit_order=2)

    def past_visit(self, title, floors, event_date=None, sent=None):
        """A visit already sent (send() refuses a date in the past)."""
        campaign = Campaign.objects.create(
            title=title,
            body="B",
            author=self.nadia,
            type=MessageType.VISIT,
            reply_type=ReplyType.ATTENDANCE,
            status=Campaign.Status.SENT,
            event_date=event_date,
            send_at=sent,
            started_at=sent,
            sent_at=sent,
        )
        campaign.floors.set(floors)
        return campaign

    def visit(self, title, floors, **kw):
        kw.setdefault("reply_type", ReplyType.ATTENDANCE)
        return self.send(title, type=MessageType.VISIT, floors=floors, **kw)

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
        Campaign.objects.create(
            title="Coupure d'eau",
            body="B",
            author=self.nadia,
            everyone=True,
            status=Campaign.Status.SCHEDULED,
            send_at=timezone.now() - timedelta(hours=1),
        )
        self.past_visit(
            "Visite 1er", [self.f1], event_date=timezone.localdate() - timedelta(days=9)
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
        self.assertIn("En attente, pas parti", page)
        # Rotation: 1er, 3e (visited), 4e: the next one is the 4th floor.
        self.assertIn(f"?etage={self.f4.pk}", page)
        self.assertIn("Préparer la visite : 4e étage", page)

    def test_rotation_order(self):
        steps = services.rotation()
        self.assertEqual([s.floor for s in steps], [self.f1, self.f3, self.f4])
        self.assertTrue(steps[0].is_next)  # never visited: the first one
        self.visit("Visite 4e", [self.f4])
        steps = services.rotation()
        self.assertTrue(steps[2].is_last)
        self.assertTrue(steps[0].is_next)  # after the last floor: back to the first

    def test_next_visit_prefilled(self):
        log_in_verified(self.client, self.nadia)
        response = self.client.get(reverse("messaging:new"), {"etage": self.f4.pk})
        form = response.context["form"]
        self.assertEqual(form.instance.type, MessageType.VISIT)
        self.assertEqual(form.initial["floors"], [self.f4.pk])
        for wrong in ("x", "²", "-1", "0", "99999999999999999999"):
            with self.subTest(wrong=wrong):
                response = self.client.get(reverse("messaging:new"), {"etage": wrong})
                self.assertEqual(response.status_code, 200)
                response = self.client.get(reverse("messaging:new"), {"modele": wrong})
                self.assertEqual(response.status_code, 200)

    def test_next_visit_uses_the_visit_template_that_asks(self):
        from messaging.models import MessageTemplate

        # The cancel notice first: the lower number must not win.
        MessageTemplate.objects.filter(type=MessageType.VISIT).delete()
        MessageTemplate.objects.create(
            name="Visite annulée", type=MessageType.VISIT, title="Visite annulée", body="B"
        )
        MessageTemplate.objects.create(
            name="Visite",
            type=MessageType.VISIT,
            title="Visite le {date}",
            body="B",
            reply_expected=True,
        )
        log_in_verified(self.client, self.nadia)
        response = self.client.get(reverse("messaging:new"), {"etage": self.f4.pk})
        self.assertEqual(response.context["form"].instance.title, "Visite le {date}")
        self.assertEqual(response.context["form"].instance.reply_type, ReplyType.ATTENDANCE)

    def test_rotation_last_visit_wins(self):
        today = timezone.localdate()
        # 3rd floor: an old dated visit, then one sent today without a date.
        now = timezone.now()
        self.past_visit("Ancienne", [self.f3], event_date=today - timedelta(days=60))
        self.past_visit("Aujourd'hui", [self.f3], sent=now)
        self.past_visit("Il y a 3 jours", [self.f1], event_date=today - timedelta(days=3))
        steps = {s.floor: s for s in services.rotation()}
        self.assertTrue(steps[self.f3].is_last)
        self.assertTrue(steps[self.f4].is_next)

    def test_rotation_one_visit_for_two_floors(self):
        # Floors 1 and 3 the same day: the rotation goes on after the 3rd.
        self.visit("Visite 1er et 3e", [self.f1, self.f3])
        steps = {s.floor: s for s in services.rotation()}
        self.assertTrue(steps[self.f3].is_last)
        self.assertTrue(steps[self.f4].is_next)

    def test_rotation_ignores_cancel_notices_and_empty_floors(self):
        self.visit("Visite annulée", [self.f1], reply_type=ReplyType.NONE)
        steps = services.rotation()
        self.assertNotIn(self.f0, [s.floor for s in steps])
        self.assertTrue(steps[0].is_next)
        self.assertIsNone(steps[0].last_visit)

    def test_stuck_message_flagged(self):
        Campaign.objects.create(
            title="Coupure d'eau",
            body="B",
            author=self.nadia,
            everyone=True,
            status=Campaign.Status.SCHEDULED,
            send_at=timezone.now() - timedelta(hours=1),
        )
        figures = {f.label: f for f in services.figures(self.nadia, timezone.now())}
        self.assertEqual(figures["Messages programmés"].value, 1)
        self.assertTrue(figures["Messages programmés"].warn)
        log_in_verified(self.client, self.nadia)
        response = self.client.get(HOME)
        self.assertContains(response, "En attente, pas parti")

    def test_titles_are_filled(self):
        day = timezone.localdate() + timedelta(days=2)
        self.visit("Visite le {date}", [self.f3], event_date=day)
        log_in_verified(self.client, self.nadia)
        response = self.client.get(HOME)
        self.assertNotContains(response, "{date}")

    def test_queries_do_not_grow(self):
        log_in_verified(self.client, self.nadia)
        self.client.get(HOME)
        for number in range(5, 10):
            floor = Floor.objects.create(number=number, visit_order=number)
            Stay.objects.create(
                resident=make_user(f"r{number}"),
                room=Room.objects.create(number=f"{number}01", floor=floor),
            )
            self.past_visit(f"Visite {number}", [floor], event_date=timezone.localdate())
            self.report()
        with self.assertNumQueries(24):
            self.client.get(HOME)

    def test_who_sees_what(self):
        log_in_verified(self.client, self.ines)  # a resident never
        self.assertEqual(self.client.get(HOME).status_code, 403)
        maintenance = make_user("theo", Role.MAINTENANCE)
        log_in_verified(self.client, maintenance)
        response = self.client.get(HOME)
        self.assertContains(response, "Signalements ouverts")
        self.assertNotContains(response, "Wifi à renouveler")
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
