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
        self.assertRedirects(
            response, self.write_url(self.samia) + "#last-message", fetch_redirect_response=False
        )
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
            '<span class="counter"><span aria-hidden="true">1</span>'
            '<span class="visually-hidden">1 message non lu</span></span>',
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

        from ..tasks import notify_message_task

        conversation = Conversation.objects.create(resident=self.ines, educator=self.samia)
        message = DirectMessage.objects.create(
            conversation=conversation, author=self.samia, text="x"
        )
        self.push.side_effect = ImproperlyConfigured("no VAPID key")
        with self.assertLogs("appointments.tasks", "WARNING"):
            notify_message_task.call(message_id=message.pk)
        self.ines.is_active = False
        self.ines.save()
        self.push.reset_mock()
        notify_message_task.call(message_id=message.pk)
        self.push.assert_not_called()
        notify_message_task.call(message_id=999999)  # deleted meanwhile: nothing


class ReviewTests(DirectTestCase):
    """Cases raised by the independent review of T28."""

    def test_the_task_queue_holds_no_name(self):
        conversation = Conversation.objects.create(resident=self.ines, educator=self.samia)
        with mock.patch("appointments.tasks.notify_message_task") as task:
            with self.captureOnCommitCallbacks(execute=True):
                direct.send(conversation, self.ines, "Bonjour")
        self.assertEqual(
            task.enqueue.call_args.kwargs, {"message_id": DirectMessage.objects.get().pk}
        )

    def test_one_notification_until_read(self):
        conversation = Conversation.objects.create(resident=self.ines, educator=self.samia)
        with self.captureOnCommitCallbacks(execute=True):
            direct.send(conversation, self.ines, "Un")
            direct.send(conversation, self.ines, "Deux")
        self.assertEqual(self.push.call_count, 1)
        direct.mark_read(conversation, self.samia)
        with self.captureOnCommitCallbacks(execute=True):
            direct.send(conversation, self.ines, "Trois")
        self.assertEqual(self.push.call_count, 2)

    def test_counters_follow_the_role_and_the_educator(self):
        conversation = Conversation.objects.create(resident=self.ines, educator=self.samia)
        DirectMessage.objects.create(conversation=conversation, author=self.samia, text="x")
        self.assertEqual(direct.unread_count(self.ines), 1)
        self.samia.is_active = False
        self.samia.save()
        self.assertEqual(direct.unread_count(self.ines), 0)  # cannot be opened any more
        self.samia.is_active = True
        self.samia.save()
        # Inès joins the staff: her resident conversations no longer count.
        from accounts.roles import set_roles

        set_roles(self.ines, [Role.FRONT_DESK])
        self.assertEqual(direct.unread_count(type(self.ines).objects.get(pk=self.ines.pk)), 0)

    def test_no_message_to_someone_who_left(self):
        conversation = Conversation.objects.create(resident=self.ines, educator=self.samia)
        DirectMessage.objects.create(conversation=conversation, author=self.ines, text="x")
        self.ines.is_active = False
        self.ines.save()
        with self.assertRaisesMessage(direct.MessageRefused, "n'a plus de compte actif"):
            direct.send(conversation, self.samia, "Réponse")
        log_in_verified(self.client, self.samia)
        page = reverse("appointments:conversation", args=[conversation.pk])
        response = self.client.get(page)
        self.assertContains(response, "Cette personne a quitté la résidence")
        self.assertNotContains(response, "Votre réponse")
        self.assertContains(response, "<title>Message direct")  # never the name in history

    def test_hostile_text(self):
        conversation = Conversation.objects.create(resident=self.ines, educator=self.samia)
        for text in ("a\x00b", "\u200b\u200b", "\u2066 \u2069"):
            with self.assertRaises(direct.MessageRefused):
                direct.send(conversation, self.ines, text)
        message = direct.send(conversation, self.ines, "a\r\n\r\n\r\n\r\nb")
        self.assertEqual(message.text, "a\n\nb")
        # Windows line breaks count once, as in the browser.
        text = ("x" * 99 + "\r\n") * 19 + "x" * 99
        self.assertEqual(len(direct.send(conversation, self.ines, text).text), 1999)
        with self.assertRaises(direct.MessageRefused):
            direct.send(conversation, self.yanis, "Je ne suis pas dans cette conversation")

    def test_limit_across_conversations(self):
        conversations = [
            Conversation.objects.create(resident=self.ines, educator=educator)
            for educator in (self.samia, self.julien)
        ]
        for conversation in conversations:
            DirectMessage.objects.bulk_create(
                DirectMessage(conversation=conversation, author=self.ines, text="x")
                for _ in range(direct.MAX_PER_DAY_IN_ALL // 2)
            )
        third = make_user("karim", Role.EDUCATOR, first_name="Karim")
        with self.assertRaisesMessage(direct.MessageRefused, "beaucoup de messages"):
            direct.send(None, self.ines, "Bonjour", resident=self.ines, educator=third)

    def test_write_to_an_educator_without_open_times(self):
        log_in_verified(self.client, self.ines)
        response = self.client.get(reverse("rdv:book"))
        self.assertContains(response, "Écrire à un éducateur")
        self.assertContains(response, f'href="{self.write_url(self.samia)}"')

    def test_new_marker_and_cache_headers(self):
        conversation = Conversation.objects.create(resident=self.ines, educator=self.samia)
        DirectMessage.objects.create(conversation=conversation, author=self.samia, text="Nouvelle")
        log_in_verified(self.client, self.ines)
        response = self.client.get(self.write_url(self.samia))
        self.assertContains(response, '<strong class="thread__new">Nouveau</strong>')
        self.assertIn("no-store", response["Cache-Control"])
        self.assertNotContains(self.client.get(self.write_url(self.samia)), "thread__new")
        self.assertIn("no-store", self.client.get(reverse("rdv:book"))["Cache-Control"])
