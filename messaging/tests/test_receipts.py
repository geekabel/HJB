"""Delivery receipts of the SMS (card T24)."""

from datetime import date, timedelta
from unittest import mock

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user
from housing.models import Floor, Room, Stay
from push.models import PushSubscription
from push.services import SendResult
from sms.providers.base import ConfigurationError, DeliveryState, Receipt, SendError
from sms.providers.base import SendResult as SmsResult
from tools.html_capture import save_page

from .. import receipts, sending
from ..models import Campaign, Delivery, EarlyReceipt
from ..models import Receipt as State

ARRIVAL = date(2026, 9, 1)
SECRET = "s3cret-" + "x" * 40


class FakeGate:
    """A provider that answers when asked, like SMSGate."""

    name = "smsgate"
    can_poll = True

    def __init__(self, answers):
        self.answers = answers  # message id -> Receipt or exception
        self.asked = []

    def missing_options(self):
        return []

    def receipt(self, message_id):
        self.asked.append(message_id)
        answer = self.answers[message_id]
        if isinstance(answer, Exception):
            raise answer
        return answer


class ReceiptTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.nadia = make_user("nadia", Role.FRONT_DESK, first_name="Nadia")
        floor = Floor.objects.create(number=3)
        cls.people = []
        for number, name in enumerate(("Yanis", "Lina", "Omar"), start=1):
            user = make_user(name.lower(), first_name=name, phone=f"+3361111111{number}")
            Stay.objects.create(
                resident=user,
                room=Room.objects.create(number=f"30{number}", floor=floor),
                arrival=ARRIVAL,
            )
            cls.people.append(user)
        cls.ines = make_user("ines", first_name="Inès")
        Stay.objects.create(
            resident=cls.ines, room=Room.objects.create(number="312", floor=floor), arrival=ARRIVAL
        )
        PushSubscription.objects.create(
            user=cls.ines, endpoint="https://web.push.apple.com/x", p256dh="x", auth="y"
        )

    def setUp(self):
        ids = iter(f"m{n}" for n in range(1, 100))
        push = mock.patch("messaging.sending.send_to_user", return_value=SendResult(sent=1))
        sms = mock.patch(
            "messaging.sending.send_sms",
            side_effect=lambda number, text: SmsResult("smsgate", next(ids), tracked=True),
        )
        push.start()
        self.sms = sms.start()
        self.addCleanup(mock.patch.stopall)

    def send(self):
        campaign = Campaign.objects.create(
            title="Coupure d'eau", body="Mardi de 8 h à 10 h.", everyone=True, author=self.nadia
        )
        with self.captureOnCommitCallbacks(execute=True):
            sending.schedule(campaign, send_at=timezone.now(), by=self.nadia)
        campaign.refresh_from_db()
        return campaign

    def sms_of(self, campaign, user):
        return campaign.deliveries.get(recipient=user)


class PollTests(ReceiptTestCase):
    def test_sent_sms_wait_for_their_receipt(self):
        campaign = self.send()
        yanis = self.sms_of(campaign, self.people[0])
        self.assertEqual((yanis.receipt, yanis.sms_provider), (State.PENDING, "smsgate"))
        self.assertEqual(self.sms_of(campaign, self.ines).receipt, "")  # notification

    def test_poll_records_and_never_goes_back(self):
        campaign = self.send()
        ids = {u: self.sms_of(campaign, u).provider_message_id for u in self.people}
        gate = FakeGate(
            {
                ids[self.people[0]]: Receipt(DeliveryState.DELIVERED),
                ids[self.people[1]]: Receipt(
                    DeliveryState.UNDELIVERED, "Le téléphone d'envoi signale un échec."
                ),
                ids[self.people[2]]: Receipt(DeliveryState.PENDING),
            }
        )
        now = timezone.now()
        with mock.patch("messaging.receipts.active_provider", return_value=gate):
            self.assertEqual(receipts.poll(now), 3)
            # Asked again only after 5 minutes, and only the one on its way.
            self.assertEqual(receipts.poll(now + timedelta(minutes=1)), 0)
            gate.answers[ids[self.people[0]]] = Receipt(DeliveryState.PENDING)
            self.assertEqual(receipts.poll(now + timedelta(minutes=6)), 1)
        self.assertEqual(gate.asked[-1], ids[self.people[2]])
        states = {u.first_name: self.sms_of(campaign, u).receipt for u in self.people}
        self.assertEqual(
            states, {"Yanis": State.DELIVERED, "Lina": State.UNDELIVERED, "Omar": State.PENDING}
        )
        # A late "en route" never replaces a final state.
        receipts.record(campaign.deliveries.all(), Receipt(DeliveryState.PENDING, "x"))
        self.assertEqual(self.sms_of(campaign, self.people[0]).receipt, State.DELIVERED)

    def test_provider_down_stops_the_round(self):
        campaign = self.send()
        gate = FakeGate(
            {
                self.sms_of(campaign, u).provider_message_id: SendError("down", temporary=True)
                for u in self.people
            }
        )
        with (
            mock.patch("messaging.receipts.active_provider", return_value=gate),
            self.assertLogs("messaging.receipts", "WARNING"),
        ):
            self.assertEqual(receipts.poll(), 0)
        self.assertEqual(len(gate.asked), 1)  # the others wait for the next minute

    def test_other_provider_or_no_polling(self):
        campaign = self.send()
        gate = FakeGate({})
        gate.name = "ovh"  # switched provider: the old SMS are not its own
        with mock.patch("messaging.receipts.active_provider", return_value=gate):
            self.assertEqual(receipts.poll(), 0)
        gate.can_poll = False
        with mock.patch("messaging.receipts.active_provider", return_value=gate):
            self.assertEqual(receipts.poll(), 0)
        self.assertEqual(gate.asked, [])
        self.assertTrue(
            all(d.receipt == State.PENDING for d in campaign.deliveries.exclude(receipt=""))
        )

    def test_access_refused_stops_the_round_and_time_budget(self):
        campaign = self.send()
        ids = [self.sms_of(campaign, u).provider_message_id for u in self.people]
        gate = FakeGate(dict.fromkeys(ids, ConfigurationError("401")))
        with (
            mock.patch("messaging.receipts.active_provider", return_value=gate),
            self.assertLogs("messaging.receipts", "WARNING"),
        ):
            receipts.poll()
        self.assertEqual(len(gate.asked), 1)
        # A slow provider: the run stops after its time budget.
        gate = FakeGate(dict.fromkeys(ids, Receipt(DeliveryState.PENDING)))
        clock = iter([0, 5, 25, 50, 75])
        with (
            mock.patch("messaging.receipts.active_provider", return_value=gate),
            mock.patch("messaging.receipts.time.monotonic", side_effect=lambda: next(clock)),
        ):
            receipts.poll(timezone.now() + timedelta(minutes=10))
        self.assertEqual(len(gate.asked), 1)

    def test_asked_less_often_with_age(self):
        campaign = self.send()
        sent = timezone.now()
        Delivery.objects.filter(campaign=campaign).update(sent_at=sent - timedelta(hours=7))
        gate = FakeGate(
            dict.fromkeys(
                (self.sms_of(campaign, u).provider_message_id for u in self.people),
                Receipt(DeliveryState.PENDING),
            )
        )
        with mock.patch("messaging.receipts.active_provider", return_value=gate):
            self.assertEqual(receipts.poll(sent), 3)
            self.assertEqual(receipts.poll(sent + timedelta(minutes=30)), 0)  # 2 h now
            self.assertEqual(receipts.poll(sent + timedelta(hours=2)), 3)

    def test_last_check_before_unknown_and_late_answers(self):
        campaign = self.send()
        yanis = self.sms_of(campaign, self.people[0])
        gate = FakeGate(
            dict.fromkeys(
                (self.sms_of(campaign, u).provider_message_id for u in self.people),
                Receipt(DeliveryState.PENDING),
            )
        )
        gate.answers[yanis.provider_message_id] = Receipt(DeliveryState.DELIVERED)
        later = timezone.now() + timedelta(hours=49)
        with mock.patch("messaging.receipts.active_provider", return_value=gate):
            receipts.poll(later)  # asked first, then the others become "Inconnu"
            self.assertEqual(self.sms_of(campaign, self.people[0]).receipt, State.DELIVERED)
            self.assertEqual(self.sms_of(campaign, self.people[1]).receipt, State.UNKNOWN)
            # The phone was off: SMSGate still asked, every 2 hours, for a week.
            lina = self.sms_of(campaign, self.people[1]).provider_message_id
            gate.answers[lina] = Receipt(DeliveryState.DELIVERED)
            receipts.poll(later + timedelta(hours=2))
            self.assertEqual(self.sms_of(campaign, self.people[1]).receipt, State.DELIVERED)
            gate.asked.clear()
            receipts.poll(later + timedelta(days=8))
        self.assertEqual(gate.asked, [])

    def test_received_wins(self):
        campaign = self.send()
        rows = Delivery.objects.filter(pk=self.sms_of(campaign, self.people[0]).pk)
        receipts.record(rows, Receipt(DeliveryState.UNDELIVERED, "x"))
        receipts.record(rows, Receipt(DeliveryState.DELIVERED))
        self.assertEqual(rows.get().receipt, State.DELIVERED)
        receipts.record(rows, Receipt(DeliveryState.UNDELIVERED, "x"))
        self.assertEqual(rows.get().receipt, State.DELIVERED)

    def test_unknown_after_48_hours_then_a_late_answer(self):
        campaign = self.send()
        later = timezone.now() + timedelta(hours=49)
        self.assertEqual(receipts.give_up(later), 3)
        yanis = self.sms_of(campaign, self.people[0])
        self.assertEqual(
            (yanis.receipt, yanis.receipt_detail),
            (State.UNKNOWN, "Pas d'accusé de réception en 48 h."),
        )
        receipts.record(Delivery.objects.filter(pk=yanis.pk), Receipt(DeliveryState.DELIVERED))
        self.assertEqual(self.sms_of(campaign, self.people[0]).receipt, State.DELIVERED)

    def test_run_scheduled_polls(self):
        with mock.patch("messaging.management.commands.run_scheduled.poll", return_value=2) as poll:
            from django.core.management import call_command

            call_command("run_scheduled", stdout=mock.Mock())
        poll.assert_called_once()


@override_settings(SMS_RECEIPT_SECRET=SECRET)
class OvhCallbackTests(ReceiptTestCase):
    def url(self, secret=SECRET):
        return reverse("sms_receipt_ovh", args=[secret])

    def ovh_campaign(self):
        campaign = self.send()
        campaign.deliveries.exclude(receipt="").update(sms_provider="ovh")
        return campaign

    def test_status_changes(self):
        campaign = self.ovh_campaign()
        yanis = self.sms_of(campaign, self.people[0])
        lina = self.sms_of(campaign, self.people[1])
        client = Client(enforce_csrf_checks=True)
        response = client.get(
            self.url(), {"id": yanis.provider_message_id, "ptt": "4", "date": "x"}
        )
        self.assertEqual(response.status_code, 200)
        response = client.post(self.url(), {"id": lina.provider_message_id, "ptt": "23"})
        self.assertEqual(response.status_code, 200)
        yanis.refresh_from_db()
        lina.refresh_from_db()
        self.assertEqual(yanis.receipt, State.DELIVERED)
        self.assertEqual(
            (lina.receipt, lina.receipt_detail),
            (State.UNDELIVERED, "Numéro invalide, bloqué ou interdit."),
        )
        # A code missing from the published list, then "delivered".
        omar = self.sms_of(campaign, self.people[2])
        client.get(self.url(), {"id": omar.provider_message_id, "ptt": "77"})
        omar.refresh_from_db()
        self.assertEqual(omar.receipt, State.PENDING)
        client.get(self.url(), {"id": omar.provider_message_id, "ptt": "4"})
        omar.refresh_from_db()
        self.assertEqual(omar.receipt, State.DELIVERED)
        # Unknown id (an activation code), bad code: accepted, nothing changes.
        self.assertEqual(client.get(self.url(), {"id": "zzz", "ptt": "4"}).status_code, 200)
        self.assertEqual(
            client.get(self.url(), {"id": yanis.provider_message_id, "ptt": "?"}).status_code, 200
        )

    def test_secret_required(self):
        campaign = self.ovh_campaign()
        message_id = self.sms_of(campaign, self.people[0]).provider_message_id
        self.assertEqual(
            self.client.get(self.url("wrong"), {"id": message_id, "ptt": "4"}).status_code, 404
        )
        with override_settings(SMS_RECEIPT_SECRET=""):
            self.assertEqual(
                self.client.get(self.url("x"), {"id": message_id, "ptt": "4"}).status_code, 404
            )
        self.assertEqual(self.sms_of(campaign, self.people[0]).receipt, State.PENDING)

    def test_receipt_before_the_save(self):
        self.client.get(self.url(), {"id": "m1", "ptt": "4"})  # the first SMS, not saved yet
        self.assertEqual(EarlyReceipt.objects.get().message_id, "m1")
        self.sms.side_effect = lambda number, text: SmsResult("ovh", "m1", tracked=True)
        campaign = Campaign.objects.create(title="T", body="B", author=self.nadia, everyone=False)
        campaign.people.add(self.people[0])
        with self.captureOnCommitCallbacks(execute=True):
            sending.schedule(campaign, send_at=timezone.now(), by=self.nadia)
        self.assertEqual(self.sms_of(campaign, self.people[0]).receipt, State.DELIVERED)
        self.assertFalse(EarlyReceipt.objects.exists())
        # Never matched (an activation code): deleted after one hour.
        self.client.get(self.url(), {"id": "zzz", "ptt": "4"})
        receipts.give_up(timezone.now() + timedelta(hours=2))
        self.assertFalse(EarlyReceipt.objects.exists())

    def test_only_ovh_sms(self):
        campaign = self.send()  # sent by SMSGate
        message_id = self.sms_of(campaign, self.people[0]).provider_message_id
        self.client.get(self.url(), {"id": message_id, "ptt": "4"})
        self.assertEqual(self.sms_of(campaign, self.people[0]).receipt, State.PENDING)


class TrackingPageTests(ReceiptTestCase):
    def test_counts_and_people_to_warn(self):
        campaign = self.send()
        yanis, lina, omar = (self.sms_of(campaign, u) for u in self.people)
        receipts.record(Delivery.objects.filter(pk=yanis.pk), Receipt(DeliveryState.DELIVERED))
        receipts.record(
            Delivery.objects.filter(pk=lina.pk),
            Receipt(DeliveryState.UNDELIVERED, "Numéro invalide, bloqué ou interdit."),
        )
        Delivery.objects.filter(pk=omar.pk).update(
            status=Delivery.Status.FAILED,
            receipt="",
            error="Envoi incertain : le SMS est peut-être parti.",
        )
        log_in_verified(self.client, self.nadia)
        response = self.client.get(reverse("messaging:tracking", args=[campaign.pk]))
        save_page("messaging-tracking-receipts", response)
        self.assertEqual(
            {k: v for k, v in response.context["receipts"].items()},
            {"pending": 0, "delivered": 1, "undelivered": 1, "unknown": 0, "total": 2},
        )
        self.assertContains(response, "2 personnes à prévenir autrement")
        self.assertContains(
            response, "<strong>Lina</strong>, chambre 302 : Numéro invalide, bloqué ou interdit."
        )
        self.assertContains(
            response,
            "<strong>Omar</strong>, chambre 303 : Envoi incertain : le SMS est peut-être parti.",
        )
        self.assertContains(response, '<span class="badge badge--success">SMS reçu</span>')
        self.assertContains(response, '<span class="badge badge--error">SMS non reçu</span>')

    def test_one_line_per_person(self):
        campaign = self.send()
        yanis, lina, _ = (self.sms_of(campaign, u) for u in self.people)
        for delivery, kind_state in ((yanis, State.UNKNOWN), (lina, State.UNDELIVERED)):
            Delivery.objects.filter(pk=delivery.pk).update(receipt=kind_state)
        # The reminders: Yanis's SMS fails too; Lina's arrives.
        for delivery, receipt in ((yanis, State.UNDELIVERED), (lina, State.DELIVERED)):
            Delivery.objects.create(
                campaign=campaign,
                recipient=delivery.recipient,
                kind=Delivery.Kind.REMINDER,
                channel="sms",
                status="sent",
                room_number=delivery.room_number,
                title="R",
                body="B",
                receipt=receipt,
                receipt_detail="Numéro invalide, bloqué ou interdit.",
            )
        rows = receipts.to_warn(campaign)
        self.assertEqual(
            [(r.recipient.first_name, r.reason) for r in rows],
            [("Yanis", "Numéro invalide, bloqué ou interdit.")],  # the latest problem
        )
        log_in_verified(self.client, self.nadia)
        response = self.client.get(reverse("messaging:tracking", args=[campaign.pk]))
        self.assertContains(response, "1 personne à prévenir autrement")
        self.assertEqual(response.context["receipts"]["total"], 3)  # the message only

    def test_nothing_to_warn(self):
        campaign = self.send()
        campaign.deliveries.update(receipt="")
        log_in_verified(self.client, self.nadia)
        response = self.client.get(reverse("messaging:tracking", args=[campaign.pk]))
        self.assertNotContains(response, "à prévenir autrement")
        self.assertNotContains(response, "Accusés de réception")
