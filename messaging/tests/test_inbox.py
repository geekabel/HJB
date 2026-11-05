"""Inbox of the resident (card T23)."""

from datetime import date, datetime, timedelta
from unittest import mock

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user
from housing.models import Floor, Room, Stay
from push.models import PushSubscription
from push.services import SendResult
from sms.providers.base import SendResult as SmsResult
from tools.html_capture import save_page

from .. import inbox, replies, sending
from ..models import Campaign, Delivery, MessageType, ReplyType
from ..templatetags.messaging_tags import short_when

ARRIVAL = date(2026, 9, 1)
LIST = reverse("inbox:list")


class InboxTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.nadia = make_user("nadia", Role.FRONT_DESK, first_name="Nadia")
        f3 = Floor.objects.create(number=3)
        cls.f3 = f3
        cls.room = Room.objects.create(number="312", floor=f3)
        cls.ines = make_user("ines", first_name="Inès", last_name="Martin")
        cls.yanis = make_user("yanis", first_name="Yanis", phone="+33611111111")
        Stay.objects.create(resident=cls.ines, room=cls.room, arrival=ARRIVAL)
        Stay.objects.create(
            resident=cls.yanis, room=Room.objects.create(number="304", floor=f3), arrival=ARRIVAL
        )
        PushSubscription.objects.create(
            user=cls.ines, endpoint="https://web.push.apple.com/x", p256dh="x", auth="y"
        )

    def setUp(self):
        push = mock.patch("messaging.sending.send_to_user", return_value=SendResult(sent=1))
        sms = mock.patch(
            "messaging.sending.send_sms", return_value=SmsResult(provider="c", message_id="1")
        )
        push.start()
        sms.start()
        self.addCleanup(mock.patch.stopall)

    def send(self, title, type=MessageType.ANNOUNCEMENT, people=(), rooms=(), floors=(), **kw):
        data = {
            "title": title,
            "body": f"Texte de « {title} ».",
            "everyone": not (people or rooms or floors),
            "author": self.nadia,
            "type": type,
        }
        data.update(kw)
        campaign = Campaign.objects.create(**data)
        campaign.people.add(*people)
        campaign.rooms.add(*rooms)
        campaign.floors.add(*floors)
        with self.captureOnCommitCallbacks(execute=True):
            sending.schedule(campaign, send_at=timezone.now(), by=self.nadia)
        campaign.refresh_from_db()
        return campaign


class InboxPageTests(InboxTestCase):
    def test_list_newest_first_with_states(self):
        party = self.send("Soirée jeux")
        visit = self.send(
            "Visite de logement",
            type=MessageType.VISIT,
            reply_type=ReplyType.ATTENDANCE,
            event_date=timezone.localdate() + timedelta(days=2),
            floors=[self.f3],
        )
        lamp = self.send(
            "Lampe de la salle de bain", type=MessageType.MAINTENANCE, rooms=[self.room]
        )
        answered = self.send(
            "Exercice incendie",
            reply_type=ReplyType.ATTENDANCE,
            event_date=timezone.localdate() + timedelta(days=3),
        )
        replies.record(answered, self.ines, "absent")
        Delivery.objects.filter(campaign=party, recipient=self.ines).update(read_at=timezone.now())
        log_in_verified(self.client, self.ines)
        response = self.client.get(LIST)
        save_page("messaging-inbox", response)
        titles = [item.delivery.title for item in response.context["items"]]
        self.assertEqual(
            titles,
            ["Exercice incendie", "Lampe de la salle de bain", "Visite de logement", "Soirée jeux"],
        )
        self.assertContains(response, "Non lu : </span>Visite de logement")
        self.assertNotContains(response, "Non lu : </span>Soirée jeux")
        self.assertContains(response, "Pour vous · Maintenance")
        self.assertContains(response, "Réponse attendue", count=1)
        self.assertContains(response, "Votre réponse : Absent")
        self.assertContains(response, "3 messages non lus")
        self.assertContains(response, '<span class="counter">3<')
        self.assertContains(response, f'href="{reverse("inbox:message", args=[visit.pk])}"')
        self.assertContains(response, f'href="{reverse("inbox:message", args=[lamp.pk])}"')

    def test_filters(self):
        self.send("Soirée jeux")
        self.send("Visite", type=MessageType.VISIT)
        self.send("Sondage", type=MessageType.VOTE)
        self.send("Pour Inès", type=MessageType.CUSTOM, people=[self.ines])
        self.send("Pour la 312", type=MessageType.MAINTENANCE, rooms=[self.room])
        self.send("Pour le 3e", type=MessageType.MAINTENANCE, floors=[self.f3])
        log_in_verified(self.client, self.ines)
        expected = {
            "visit": ["Visite"],
            "announcement": ["Soirée jeux"],
            "vote": ["Sondage"],
            "mine": ["Pour la 312", "Pour Inès"],
            "nonsense": [
                "Pour le 3e",
                "Pour la 312",
                "Pour Inès",
                "Sondage",
                "Visite",
                "Soirée jeux",
            ],
        }
        for key, titles in expected.items():
            response = self.client.get(LIST, {"show": key})
            got = [item.delivery.title for item in response.context["items"]]
            self.assertEqual(got, titles, key)
        response = self.client.get(LIST, {"show": "mine"})
        save_page("messaging-inbox-mine", response)
        self.assertContains(response, 'aria-current="page">Pour moi</a>')
        # Yanis is on the 3rd floor too, but nothing was sent to him by name.
        log_in_verified(self.client, self.yanis)
        response = self.client.get(LIST, {"show": "mine"})
        save_page("messaging-inbox-empty", response)
        self.assertContains(response, "Aucun message qui vous est adressé personnellement.")

    def test_only_own_sent_messages(self):
        self.send("Pour Yanis", people=[self.yanis])
        Campaign.objects.create(title="Brouillon", body="B", everyone=True, author=self.nadia)
        failed = self.send("SMS en échec")
        Delivery.objects.filter(campaign=failed).update(
            status=Delivery.Status.FAILED, error="Envoi incertain : le SMS est peut-être parti."
        )
        log_in_verified(self.client, self.ines)
        response = self.client.get(LIST)
        titles = [item.delivery.title for item in response.context["items"]]
        self.assertEqual(titles, ["SMS en échec"])  # shown in the app, even when the SMS failed
        url = reverse("inbox:message", args=[failed.pk])
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_open_marks_read_then_read_all(self):
        first = self.send("Premier")
        self.send("Deuxième")
        self.send("Troisième", type=MessageType.VISIT)
        log_in_verified(self.client, self.ines)
        self.assertEqual(inbox.unread_count(self.ines), 3)
        response = self.client.get(reverse("inbox:message", args=[first.pk]))
        self.assertContains(response, f'href="{LIST}"')
        self.assertContains(response, '<span class="counter">2<')  # this one is read now
        response = self.client.post(reverse("inbox:read_all"), {"show": "visit"})
        self.assertRedirects(response, LIST + "?show=visit", fetch_redirect_response=False)
        self.assertEqual(inbox.unread_count(self.ines), 0)
        response = self.client.get(LIST)
        self.assertContains(response, "2 messages marqués comme lus.")
        self.assertNotContains(response, "Tout marquer comme lu")
        self.assertNotContains(response, 'class="counter"')
        self.assertEqual(self.client.get(reverse("inbox:read_all")).status_code, 405)

    def test_login_required(self):
        response = self.client.get(LIST)
        self.assertIn(reverse("access:login"), response["Location"])
        response = self.client.post(reverse("inbox:read_all"))
        self.assertIn(reverse("access:login"), response["Location"])

    def test_pages_and_query_count(self):
        for number in range(3):
            self.send(f"Message {number}")
        log_in_verified(self.client, self.ines)
        with CaptureQueriesContext(connection) as few:
            self.client.get(LIST)
        for number in range(3, 25):
            self.send(f"Message {number}", reply_type=ReplyType.ATTENDANCE)
        with CaptureQueriesContext(connection) as many:
            response = self.client.get(LIST)
        self.assertEqual(len(many), len(few))  # no query per message
        self.assertEqual(len(response.context["items"]), 20)
        self.assertContains(response, "Page 1 sur 2")
        response = self.client.get(LIST, {"page": 2})
        self.assertEqual(len(response.context["items"]), 5)


class ShortWhenTests(TestCase):
    def test_formats(self):
        now = timezone.make_aware(datetime(2026, 11, 5, 21, 40))  # a Thursday
        with mock.patch("django.utils.timezone.now", return_value=now):
            cases = {
                datetime(2026, 11, 5, 9, 12): "09:12",
                datetime(2026, 11, 4, 18, 0): "Hier",
                datetime(2026, 11, 2, 18, 0): "Lun.",
                datetime(2026, 10, 30, 18, 0): "Ven.",
                datetime(2026, 10, 29, 18, 0): "29 octobre",
                datetime(2025, 12, 24, 18, 0): "24 décembre 2025",
            }
            for moment, text in cases.items():
                self.assertEqual(short_when(timezone.make_aware(moment)), text)
        self.assertEqual(short_when(None), "")
