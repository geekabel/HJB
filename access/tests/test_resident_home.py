"""The resident home (card T34): the action that waits first, shortcuts,
my reports, the last announcement."""

from django.urls import reverse
from django.utils import timezone

from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user
from messaging.models import MessageType
from messaging.tests.test_inbox import InboxTestCase
from reports import handling
from reports.models import Report
from tools.html_capture import save_page

HOME = reverse("home")


class ResidentHomeTests(InboxTestCase):
    def report(self, **changes):
        data = {
            "resident": self.ines,
            "room": self.room,
            "category": "plumbing",
            "description": "Fuite sous l'évier",
            "urgency": "annoying",
            "due_at": timezone.now() + Report.DELAYS["annoying"],
        }
        return Report.objects.create(**(data | changes))

    def test_lead_shortcuts_reports_and_announcement(self):
        self.send("Soirée jeux samedi")
        marc = make_user("marc", Role.MAINTENANCE, first_name="Marc")
        done = self.report()
        handling.done(done, marc)
        open_report = self.report(category="heating")
        log_in_verified(self.client, self.ines)
        response = self.client.get(HOME)
        save_page("home-resident-full", response)
        page = response.content.decode()
        # The repair to confirm leads, with its own button.
        self.assertIn("Signalement · réponse attendue", page)
        self.assertIn("Plomberie : c&#x27;est réglé ?", page)
        self.assertIn(f'href="{reverse("reports:detail", args=[done.pk])}">Répondre', page)
        self.assertIn("Chambre 312", page)
        # Shortcuts, my reports (open ones), the last announcement.
        self.assertIn('aria-label="Raccourcis"', page)
        self.assertIn("Mes signalements", page)
        self.assertIn(reverse("reports:detail", args=[open_report.pk]), page)
        self.assertIn("Dernière annonce", page)
        self.assertIn("Soirée jeux samedi", page)
        self.assertNotIn("Rien à faire", page)

    def test_a_vote_leads_before_the_repair(self):
        self.send("Couleur de la salle commune", type=MessageType.VOTE)
        done = self.report()
        handling.done(done, make_user("marc", Role.MAINTENANCE))
        log_in_verified(self.client, self.ines)
        response = self.client.get(HOME)
        page = response.content.decode()
        self.assertIn("Vote ouvert", page)
        self.assertLess(page.index("Couleur de la salle commune"), page.index("Aussi à faire"))
        self.assertIn("Plomberie : c&#x27;est réglé ?", page)

    def test_quiet_home(self):
        self.report(status=Report.Status.CLOSED)
        log_in_verified(self.client, self.ines)
        response = self.client.get(HOME)
        self.assertContains(response, "Rien à faire pour le moment.")
        self.assertNotContains(response, "Mes signalements")
        self.assertNotContains(response, "Dernière annonce")


class ResidentHomeReviewTests(ResidentHomeTests):
    """Independent review of T34."""

    def meeting(self, hours):
        from datetime import timedelta

        from appointments.models import Appointment

        samia = make_user(f"samia{hours}", Role.EDUCATOR, first_name="Samia")
        start = timezone.now() + timedelta(hours=hours)
        return Appointment.objects.create(
            educator=samia, resident=self.ines, start=start, end=start + timedelta(minutes=30)
        )

    def test_only_answers_are_cut_and_what_is_due_today_leads(self):
        from datetime import timedelta

        from messaging.models import ReplyType

        soon = timezone.localdate() + timedelta(days=2)
        for n in range(7):
            self.send(f"Visite {n}", reply_type=ReplyType.ATTENDANCE, event_date=soon)
        today_hours = 23 - timezone.localtime().hour
        meeting = self.meeting(1 if today_hours >= 1 else 30)
        log_in_verified(self.client, self.ines)
        response = self.client.get(HOME)
        lead, others = response.context["lead"], response.context["todos"]
        titles = [lead.title] + [todo.title for todo in others]
        self.assertIn("Rendez-vous avec Samia", titles)  # never cut
        self.assertEqual(sum(t.startswith("Visite") for t in titles), 5)
        self.assertContains(response, "Voir les autres messages à répondre (2)")
        if timezone.localtime(meeting.start).date() == timezone.localdate():
            self.assertEqual(lead.title, "Rendez-vous avec Samia")  # due today: first
            self.assertContains(response, ">Voir le rendez-vous</a>")

    def test_labels_of_each_kind(self):
        from appointments import direct

        samia = make_user("samia", Role.EDUCATOR, first_name="Samia")
        conversation = direct.Conversation.objects.create(resident=self.ines, educator=samia)
        direct.DirectMessage.objects.create(conversation=conversation, author=samia, text="Salut")
        log_in_verified(self.client, self.ines)
        response = self.client.get(HOME)
        self.assertEqual(response.context["lead"].lead, "Message d'un éducateur")
        self.assertContains(response, ">Lire</a>")

    def test_without_a_stay_and_others_hidden(self):
        nomad = make_user("nomad", first_name="Sans")
        self.send("Soirée jeux samedi", people=[self.ines])
        self.report()
        log_in_verified(self.client, nomad)
        response = self.client.get(HOME)
        self.assertNotContains(response, "Chambre")
        self.assertNotContains(response, "Mes signalements")
        self.assertNotContains(response, "Soirée jeux")
        self.assertIsNone(response.context["lead"])

    def test_old_announcement_ages_out(self):
        from datetime import timedelta

        from messaging.models import Delivery

        campaign = self.send("Fête des voisins")
        Delivery.objects.filter(campaign=campaign).update(
            sent_at=timezone.now() - timedelta(days=40)
        )
        log_in_verified(self.client, self.ines)
        self.assertNotContains(self.client.get(HOME), "Dernière annonce")

    def test_query_count(self):
        self.send("Soirée jeux samedi")
        self.report()
        log_in_verified(self.client, self.ines)
        self.client.get(HOME)
        with self.assertNumQueries(17):  # as before T34: the stay is read once
            self.client.get(HOME)
