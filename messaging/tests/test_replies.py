"""Answer "Présent" or "Absent" (card T22)."""

import json
from datetime import date, datetime, time, timedelta
from unittest import mock

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user
from housing.models import Floor, Room, Stay
from push.models import PushSubscription
from push.services import SendResult, _payload
from sms.providers.base import SendResult as SmsResult
from tools.html_capture import save_page

from .. import replies, sending
from ..models import AttendanceReply, Campaign, Delivery, ReplyType

ARRIVAL = date(2026, 9, 1)


class ReplyTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.nadia = make_user("nadia", Role.FRONT_DESK, first_name="Nadia")
        f3 = Floor.objects.create(number=3)
        cls.ines = make_user("ines", first_name="Inès", last_name="Martin")
        cls.yanis = make_user("yanis", first_name="Yanis", phone="+33611111111")
        Stay.objects.create(
            resident=cls.ines, room=Room.objects.create(number="312", floor=f3), arrival=ARRIVAL
        )
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
        self.push = push.start()
        self.sms = sms.start()
        self.addCleanup(mock.patch.stopall)

    def sent_campaign(self, people=(), **kwargs):
        data = {
            "title": "Visite de logement",
            "body": "Bonjour {prénom}, visite le {date}.",
            "sms_body": "Bonjour {prénom}, visite le {date}.",
            "everyone": True,
            "author": self.nadia,
            "reply_type": ReplyType.ATTENDANCE,
            "event_date": timezone.localdate() + timedelta(days=2),
        }
        data.update(kwargs)
        campaign = Campaign.objects.create(**data)
        campaign.people.add(*people)
        with self.captureOnCommitCallbacks(execute=True):
            sending.schedule(campaign, send_at=timezone.now(), by=self.nadia)
        campaign.refresh_from_db()
        return campaign

    def link(self, campaign, user):
        return replies.reply_path(campaign.pk, user.pk)


class TokenTests(ReplyTestCase):
    def test_round_trip_and_tampering(self):
        token = replies.make_token(12, 345)
        self.assertEqual(replies.read_token(token), (12, 345))
        self.assertLessEqual(len(token), 20)
        campaign, user, signature = token.split("-", 2)
        for forged in (
            f"{campaign}-{replies.make_token(12, 346).split('-')[1]}-{signature}",  # another person
            f"{campaign}-{user}-{signature[:-1]}{'B' if signature.endswith('A') else 'A'}",
            f"{campaign}-{user}",
            "zz-zz-" + "a" * 60,
            "not a token",
            "",
        ):
            self.assertIsNone(replies.read_token(forged), forged)

    @override_settings(SECRET_KEY="another-secret-key-for-this-test-only-xxxxxxxxxxxxxxxxxx")
    def test_depends_on_the_secret_key(self):
        token = replies.make_token(12, 345)
        with override_settings(SECRET_KEY="yet-another-secret-key-for-this-test-xxxxxxxxxxxxxxxxx"):
            self.assertIsNone(replies.read_token(token))

    @override_settings(SECRET_KEY="old-secret-key-for-this-test-only-xxxxxxxxxxxxxxxxxxxxxxx")
    def test_old_links_survive_a_key_change(self):
        token = replies.make_token(12, 345)
        with override_settings(
            SECRET_KEY="new-secret-key-for-this-test-only-xxxxxxxxxxxxxxxxxxxxxxx",
            SECRET_KEY_FALLBACKS=["old-secret-key-for-this-test-only-xxxxxxxxxxxxxxxxxxxxxxx"],
        ):
            self.assertEqual(replies.read_token(token), (12, 345))


class SendingTests(ReplyTestCase):
    def test_sms_ends_with_the_personal_link(self):
        campaign = self.sent_campaign()
        text = self.sms.call_args.args[1]
        expected = "http://localhost:8000" + self.link(campaign, self.yanis)
        self.assertTrue(text.endswith(f" Présent ou absent ? Répondez : {expected}"), text)
        delivery = campaign.deliveries.get(recipient=self.yanis)
        self.assertEqual(delivery.segments, 1)

    def test_notification_gets_the_buttons(self):
        campaign = self.sent_campaign()
        kwargs = self.push.call_args.kwargs
        self.assertEqual(kwargs["reply"], self.link(campaign, self.ines))
        self.assertEqual(kwargs["url"], reverse("inbox:message", args=[campaign.pk]))
        payload = json.loads(_payload("t", "b", "/", "", kwargs["reply"]))
        self.assertEqual(payload["reply"], kwargs["reply"])
        with self.assertRaises(ValueError):
            _payload("t", "b", "/", "", "https://evil.example/r/x/")

    def test_no_link_without_a_question(self):
        self.sent_campaign(reply_type=ReplyType.NONE)
        self.assertNotIn("Répondez", self.sms.call_args.args[1])
        self.assertEqual(self.push.call_args.kwargs["reply"], "")

    def test_link_counts_in_the_composer(self):
        log_in_verified(self.client, self.nadia)
        campaign = Campaign.objects.create(
            title="Visite",
            body="Bonjour",
            everyone=True,
            author=self.nadia,
            reply_type=ReplyType.ATTENDANCE,
        )
        response = self.client.get(reverse("messaging:compose", args=[campaign.pk]))
        self.assertContains(response, "Présent ou absent ? Répondez : http://localhost:8000/r/")

    @override_settings(SITE_URL="")
    def test_site_address_needed(self):
        campaign = Campaign.objects.create(
            title="V", body="B", everyone=True, author=self.nadia, reply_type="attendance"
        )
        self.assertIn(
            "L'adresse du site n'est pas réglée (DJANGO_SITE_URL) : pas de lien de réponse.",
            sending.problems(campaign, timezone.now()),
        )

    def test_event_day_already_over(self):
        today = timezone.localdate()
        campaign = Campaign.objects.create(
            title="V",
            body="B",
            everyone=True,
            author=self.nadia,
            reply_type=ReplyType.ATTENDANCE,
            event_date=today - timedelta(days=1),
        )
        message = "La date du message est passée ou trop proche : plus de réponse possible."
        self.assertIn(message, sending.problems(campaign, timezone.now()))
        late = timezone.make_aware(datetime.combine(today, time(23, 30)))
        campaign.event_date = today
        self.assertIn(message, sending.problems(campaign, late))
        campaign.event_date = today + timedelta(days=1)
        self.assertNotIn(message, sending.problems(campaign, late))

    def test_reminder_skips_those_who_answered_by_the_link(self):
        event = timezone.localdate() + timedelta(days=2)
        campaign = self.sent_campaign(remind=True, event_date=event)
        Client().post(self.link(campaign, self.yanis), {"answer": "absent"})
        when = timezone.make_aware(datetime.combine(event, time(8, 1)))
        with mock.patch("django.utils.timezone.now", return_value=when):
            sending.run_due(when)
        reminders = campaign.deliveries.filter(kind=Delivery.Kind.REMINDER)
        self.assertEqual([d.recipient for d in reminders], [self.ines])


class ReplyPageTests(ReplyTestCase):
    def test_link_page_then_answer(self):
        campaign = self.sent_campaign()
        client = Client(
            enforce_csrf_checks=True
        )  # no session, no CSRF token: the link is the proof
        url = self.link(campaign, self.yanis)
        response = client.get(url)
        save_page("messaging-reply", response)
        self.assertContains(response, "Bonjour Yanis, visite le")
        self.assertContains(response, "Serez-vous présent ?")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertFalse(AttendanceReply.objects.exists())  # a preview never answers
        self.assertIsNone(campaign.deliveries.get(recipient=self.yanis).read_at)  # nor reads
        response = client.post(url, {"answer": "present"})
        save_page("messaging-reply-done", response)
        self.assertContains(response, "C&#x27;est noté : vous serez présent.")
        response = client.post(url, {"answer": "absent"})  # changed
        reply = AttendanceReply.objects.get()
        self.assertEqual((reply.resident, reply.answer), (self.yanis, "absent"))
        self.assertIsNotNone(campaign.deliveries.get(recipient=self.yanis).read_at)

    def test_closed_after_the_event_day(self):
        campaign = self.sent_campaign()
        url = self.link(campaign, self.yanis)
        after = timezone.make_aware(
            datetime.combine(campaign.event_date + timedelta(days=1), time(0, 1))
        )
        with mock.patch("django.utils.timezone.now", return_value=after):
            response = self.client.post(url, {"answer": "present"})
            self.assertEqual(response.status_code, 409)
            save_page("messaging-reply-closed", self.client.get(url))
            self.assertContains(self.client.get(url), "Les réponses à ce message sont fermées.")
        self.assertFalse(AttendanceReply.objects.exists())

    def test_uncertain_sms_still_answers(self):
        campaign = self.sent_campaign()
        campaign.deliveries.filter(recipient=self.yanis).update(
            status=Delivery.Status.FAILED, error="Envoi incertain : le SMS est peut-être parti."
        )
        response = Client().post(self.link(campaign, self.yanis), {"answer": "present"})
        self.assertContains(response, "vous serez présent")
        self.assertEqual(replies.counts(campaign)["present"], 1)

    def test_refused(self):
        campaign = self.sent_campaign()
        url = self.link(campaign, self.yanis)
        response = self.client.post(url, {"answer": "maybe"})
        self.assertContains(
            response, "Choisissez «\u00a0Présent\u00a0» ou «\u00a0Absent\u00a0».", status_code=400
        )
        self.assertNotContains(response, "fermées", status_code=400)
        self.assertEqual(self.client.get("/r/1-2-forgedsignatur/").status_code, 404)
        other = replies.reply_path(campaign.pk, self.nadia.pk)  # genuine, but not a recipient
        self.assertEqual(self.client.get(other).status_code, 404)
        self.yanis.is_active = False
        self.yanis.save()
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_message_page_in_the_app(self):
        campaign = self.sent_campaign()
        url = reverse("inbox:message", args=[campaign.pk])
        self.assertIn(reverse("access:login"), self.client.get(url)["Location"])
        log_in_verified(self.client, self.ines)
        response = self.client.get(url)
        save_page("messaging-message", response)
        self.assertContains(response, "Bonjour Inès")
        response = self.client.post(url, {"answer": "present"}, follow=True)
        self.assertContains(response, "vous serez présent")
        self.assertContains(response, "Votre réponse : <strong>Présent</strong>")
        self.assertNotContains(response, "aria-pressed")
        # Someone else's message: not found.
        other = self.sent_campaign(everyone=False, people=[self.yanis])
        log_in_verified(self.client, self.ines)
        self.assertEqual(
            self.client.get(reverse("inbox:message", args=[other.pk])).status_code, 404
        )

    def test_staff_counts(self):
        campaign = self.sent_campaign()
        replies.record(campaign, self.ines, "present")
        log_in_verified(self.client, self.nadia)
        response = self.client.get(reverse("messaging:tracking", args=[campaign.pk]))
        save_page("messaging-tracking-answers", response)
        self.assertEqual(
            {k: v for k, v in replies.counts(campaign).items() if k != "answers"},
            {"present": 1, "absent": 0, "none": 1},
        )
        self.assertContains(response, '<span class="badge badge--success">Présent</span>')
