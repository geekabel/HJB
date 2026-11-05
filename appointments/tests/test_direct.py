"""Direct messages between a resident and an educator (card T28)."""

from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user
from push.services import SendResult
from tools.html_capture import save_page

from .. import direct
from ..models import Conversation, DirectMessage, EducatorSettings


class DirectTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.samia = make_user("samia", Role.EDUCATOR, first_name="Samia")
        cls.julien = make_user("julien", Role.EDUCATOR, first_name="Julien")
        cls.nadia = make_user("nadia", Role.FRONT_DESK, first_name="Nadia")
        cls.marie = make_user("marie", Role.ADMIN, first_name="Marie")
        cls.ines = make_user("ines", first_name="Inès", last_name="Martin")
        cls.yanis = make_user("yanis", first_name="Yanis")

    def setUp(self):
        patcher = mock.patch("appointments.tasks.send_to_user", return_value=SendResult(sent=1))
        self.push = patcher.start()
        self.addCleanup(patcher.stop)

    def write_url(self, educator):
        return reverse("rdv:write", args=[educator.pk])


class ConversationTests(DirectTestCase):
    def test_resident_writes_educator_answers(self):
        log_in_verified(self.client, self.ines)
        response = self.client.get(self.write_url(self.samia))
        save_page("appointments-write-empty", response)
        self.assertContains(
            response, "Samia répond en général du lundi au vendredi, de 9 h à 17 h."
        )
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                self.write_url(self.samia),
                {"text": "Bonjour, je peux venir avec mon dossier CAF ?"},
            )
        self.assertRedirects(response, self.write_url(self.samia), fetch_redirect_response=False)
        conversation = Conversation.objects.get()
        self.assertEqual((conversation.resident, conversation.educator), (self.ines, self.samia))
        # The notification says who wrote, never the text (locked screens).
        kwargs = self.push.call_args.kwargs
        self.assertEqual(self.push.call_args.args[0], self.samia)
        self.assertEqual(
            (kwargs["title"], kwargs["body"]), ("Nouveau message", "Inès vous a écrit.")
        )
        self.assertEqual(
            kwargs["url"], reverse("appointments:conversation", args=[conversation.pk])
        )

        # The educator sees the unread message, opens it, answers.
        log_in_verified(self.client, self.samia)
        url = reverse("appointments:availability")
        self.assertContains(
            self.client.get(url),
            '<span class="counter">1<span class="visually-hidden"> message non lu',
        )
        page = reverse("appointments:conversation", args=[conversation.pk])
        response = self.client.get(page)
        save_page("appointments-conversation", response)
        self.assertContains(response, "dossier CAF")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(direct.unread_count(self.samia), 0)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(page, {"text": "Oui, bien sûr."})
        self.assertEqual(self.push.call_args.args[0], self.ines)
        self.assertEqual(self.push.call_args.kwargs["url"], self.write_url(self.samia))

        # The resident sees the answer, and the counter on "Rendez-vous".
        log_in_verified(self.client, self.ines)
        response = self.client.get(reverse("rdv:book"))
        save_page("appointments-book-messages", response)
        self.assertContains(response, "Mes messages")
        self.assertContains(response, "1 message non lu")
        response = self.client.get(self.write_url(self.samia))
        save_page("appointments-write", response)
        self.assertContains(response, "Oui, bien sûr.")
        self.assertEqual(direct.unread_count(self.ines), 0)

    def test_only_the_two_people(self):
        conversation = Conversation.objects.create(resident=self.ines, educator=self.samia)
        DirectMessage.objects.create(conversation=conversation, author=self.ines, text="Privé")
        page = reverse("appointments:conversation", args=[conversation.pk])
        log_in_verified(self.client, self.julien)
        self.assertEqual(self.client.get(page).status_code, 404)  # another educator
        self.assertNotContains(self.client.get(reverse("appointments:conversations")), "Inès")
        log_in_verified(self.client, self.marie)
        self.assertEqual(self.client.get(page).status_code, 404)  # administration too
        log_in_verified(self.client, self.nadia)
        self.assertEqual(self.client.get(page).status_code, 403)  # no appointments right
        # Yanis writing to Samia gets his own conversation, never Inès's.
        log_in_verified(self.client, self.yanis)
        self.assertNotContains(self.client.get(self.write_url(self.samia)), "Privé")

    def test_who_can_be_written_to(self):
        log_in_verified(self.client, self.ines)
        self.assertEqual(self.client.get(self.write_url(self.marie)).status_code, 404)
        self.assertEqual(self.client.get(self.write_url(self.yanis)).status_code, 404)
        self.samia.is_active = False
        self.samia.save()
        self.assertEqual(self.client.get(self.write_url(self.samia)).status_code, 404)
        log_in_verified(self.client, self.julien)
        self.assertRedirects(
            self.client.get(self.write_url(self.samia)),
            reverse("home"),
            fetch_redirect_response=False,
        )

    def test_refused_messages(self):
        log_in_verified(self.client, self.ines)
        url = self.write_url(self.samia)
        response = self.client.post(url, {"text": "   "})
        self.assertContains(response, "Écrivez un message avant d&#x27;envoyer.")
        long = "x" * (direct.MAX_LENGTH + 1)
        response = self.client.post(url, {"text": long})
        self.assertContains(response, "trop long")
        self.assertFalse(DirectMessage.objects.exists())

    def test_daily_limit(self):
        conversation = Conversation.objects.create(resident=self.ines, educator=self.samia)
        DirectMessage.objects.bulk_create(
            DirectMessage(conversation=conversation, author=self.ines, text="x")
            for _ in range(direct.MAX_PER_DAY)
        )
        with self.assertRaisesMessage(direct.MessageRefused, "beaucoup de messages"):
            direct.send(conversation, self.ines, "Encore un")
        DirectMessage.objects.update(sent_at=timezone.now() - timedelta(days=2))
        direct.send(conversation, self.ines, "Le lendemain")  # the limit is per 24 hours
        direct.send(conversation, self.samia, "Réponse")  # the educator has their own count

    def test_reply_hours_setting(self):
        log_in_verified(self.client, self.samia)
        self.client.post(
            reverse("appointments:availability"),
            {"slot_minutes": "30", "notice": "2h", "reply_hours": "le mardi et le jeudi"},
        )
        self.assertEqual(EducatorSettings.objects.get().reply_hours, "le mardi et le jeudi")
        log_in_verified(self.client, self.ines)
        self.assertContains(
            self.client.get(self.write_url(self.samia)),
            "Samia répond en général le mardi et le jeudi.",
        )

    def test_notification_task_is_best_effort(self):
        from django.core.exceptions import ImproperlyConfigured

        from ..tasks import notify_task

        self.push.side_effect = ImproperlyConfigured("no VAPID key")
        with self.assertLogs("appointments.tasks", "WARNING"):
            notify_task.call(user_id=self.ines.pk, title="t", body="b", url="/", tag="x")
        self.ines.is_active = False
        self.ines.save()
        self.push.reset_mock()
        notify_task.call(user_id=self.ines.pk, title="t", body="b", url="/", tag="x")
        self.push.assert_not_called()
