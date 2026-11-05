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
from polls.models import Poll
from polls.services import set_options
from push.models import PushSubscription
from push.services import SendResult
from sms.providers.base import SendResult as SmsResult
from tools.html_capture import save_page

from .. import inbox, replies, sending
from ..models import Campaign, Delivery, MessageType, ReplyType
from ..templatetags.messaging_tags import short_when

ARRIVAL = date(2026, 9, 1)
LIST = reverse("inbox:list")
COUNTER = (
    '<span class="counter"><span aria-hidden="true">{}</span>'
    '<span class="visually-hidden">{}</span></span>'
)


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
        if type == MessageType.VOTE:  # a vote needs its poll (card T25)
            poll = Poll.objects.create(
                campaign=campaign, closes_at=timezone.now() + timedelta(days=2)
            )
            set_options(poll, ["Oui", "Non"])
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
        self.assertContains(response, "Non lu&nbsp;: </span>Visite de logement")
        self.assertNotContains(response, "Non lu&nbsp;: </span>Soirée jeux")
        self.assertContains(response, "Pour vous · Maintenance")
        self.assertContains(response, "Réponse attendue", count=1)
        self.assertContains(response, "Votre réponse&nbsp;: Absent")
        self.assertContains(response, "3 messages non lus")
        self.assertContains(response, COUNTER.format(3, "3 non lus"))
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
        self.assertContains(response, COUNTER.format(2, "2 non lus"))  # this one is read now
        # From a filter: only the messages of that list, the others were not seen.
        response = self.client.get(LIST, {"show": "visit"})
        self.assertContains(response, "1 message non lu dans cette liste")
        response = self.client.post(reverse("inbox:read_all"), {"show": "visit"})
        self.assertRedirects(response, LIST + "?show=visit", fetch_redirect_response=False)
        self.assertEqual(inbox.unread_count(self.ines), 1)
        self.assertContains(self.client.get(LIST, {"show": "visit"}), "1 message marqué comme lu.")
        self.client.post(reverse("inbox:read_all"), {"show": "../evil"})  # unknown: all
        self.assertEqual(inbox.unread_count(self.ines), 0)
        response = self.client.get(LIST)
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


class InboxEdgeTests(InboxTestCase):
    def test_hidden_and_other_people(self):
        message = self.send(
            "Visite",
            reply_type=ReplyType.ATTENDANCE,
            event_date=timezone.localdate() + timedelta(days=2),
        )
        Delivery.objects.create(  # a reminder is not a second message
            campaign=message,
            recipient=self.ines,
            kind=Delivery.Kind.REMINDER,
            channel="push",
            title="Rappel : Visite",
            body="B",
        )
        cancelled = self.send("Annulé ensuite")
        Campaign.objects.filter(pk=cancelled.pk).update(status=Campaign.Status.CANCELLED)
        log_in_verified(self.client, self.ines)
        titles = [item.delivery.title for item in self.client.get(LIST).context["items"]]
        self.assertEqual(titles, ["Visite"])
        self.assertEqual(inbox.unread_count(self.ines), 1)
        url = reverse("inbox:message", args=[cancelled.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        # Marking everything as read leaves the other residents alone.
        self.client.post(reverse("inbox:read_all"))
        self.assertTrue(
            Delivery.objects.filter(recipient=self.yanis, read_at__isnull=True).exists()
        )

    def test_failed_delivery_is_unread_and_waits_for_an_answer(self):
        campaign = self.send(
            "Visite",
            reply_type=ReplyType.ATTENDANCE,
            event_date=timezone.localdate() + timedelta(days=2),
        )
        Delivery.objects.filter(campaign=campaign).update(status=Delivery.Status.FAILED)
        log_in_verified(self.client, self.ines)
        response = self.client.get(LIST)
        self.assertContains(response, "Réponse attendue")
        self.assertEqual(inbox.unread_count(self.ines), 1)

    def test_sorted_by_the_time_received(self):
        late = self.send("Parti en retard")
        on_time = self.send("Parti à l'heure")
        Delivery.objects.filter(campaign=late).update(
            sent_at=timezone.now() + timedelta(minutes=25)
        )
        log_in_verified(self.client, self.ines)
        items = self.client.get(LIST).context["items"]
        self.assertEqual([i.delivery.title for i in items], ["Parti en retard", "Parti à l'heure"])
        self.assertEqual(items[1].when, on_time.deliveries.get(recipient=self.ines).sent_at)

    def test_for_me_is_decided_at_send_time(self):
        by_room = self.send("Pour la 312", rooms=[self.room])
        both = self.send("Tous et Inès", everyone=True, people=[self.ines])
        floor_and_name = self.send("Étage et Inès", floors=[self.f3], people=[self.ines])
        get = lambda c, u=self.ines: Delivery.objects.get(campaign=c, recipient=u)  # noqa: E731
        self.assertTrue(get(by_room).personal)
        self.assertFalse(get(both).personal)  # everyone: not personal
        self.assertTrue(get(floor_and_name).personal)
        self.assertFalse(get(floor_and_name, self.yanis).personal)
        # The room is renamed, or Inès moves: the message stays hers.
        Room.objects.filter(pk=self.room.pk).update(number="312A")
        self.assertIn(get(by_room), inbox.inbox(self.ines, "mine"))

    def test_counter_caps_and_staff(self):
        campaigns = [
            Campaign(
                title=f"M{n}",
                body="b",
                everyone=True,
                author=self.nadia,
                status=Campaign.Status.SENT,
                started_at=timezone.now(),
            )
            for n in range(100)
        ]
        Campaign.objects.bulk_create(campaigns)
        Delivery.objects.bulk_create(
            Delivery(campaign=c, recipient=self.ines, channel="push", title=c.title, body="b")
            for c in Campaign.objects.filter(title__startswith="M")
        )
        log_in_verified(self.client, self.ines)
        response = self.client.get(reverse("home"))
        self.assertContains(response, COUNTER.format("99+", "100 non lus"))
        self.assertContains(response, 'Messages<span class="visually-hidden">, </span>')
        log_in_verified(self.client, self.nadia)
        self.assertRedirects(self.client.get(LIST), reverse("home"), target_status_code=302)

    def test_bar_count_is_not_repeated(self):
        self.send("Un")
        log_in_verified(self.client, self.ines)
        with CaptureQueriesContext(connection) as queries:
            self.client.get(LIST)
        counts = [q["sql"] for q in queries if q["sql"].startswith("SELECT COUNT(")]
        # The pages, the unread ones, and the unread direct messages of the
        # "Rendez-vous" entry of the bar (card T28).
        self.assertEqual(len(counts), 3)
        self.assertEqual(self.client.head(LIST).status_code, 200)
