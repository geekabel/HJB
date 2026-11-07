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
