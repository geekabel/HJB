"""Sending now or later, reminders, planned departures (card T21)."""

import io
from datetime import date, datetime, time, timedelta
from unittest import mock

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user
from audit.models import Action, AuditEntry
from housing.models import Floor, Room, Stay
from push.models import PushSubscription
from push.services import SendResult
from sms.providers.base import SendError
from sms.providers.base import SendResult as SmsResult
from tools.html_capture import save_page

from .. import sending
from ..models import AttendanceReply, Campaign, Delivery, ReplyType

ARRIVAL = date(2026, 9, 1)
PUSHED = SendResult(sent=1)
NOT_PUSHED = SendResult()
SMS_OK = SmsResult(provider="console", message_id="abc-1")


def at(day, hour, minute=0):
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


class SendingTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.nadia = make_user("nadia", Role.FRONT_DESK, first_name="Nadia")
        f3 = Floor.objects.create(number=3)
        cls.f3 = f3
        cls.r312 = Room.objects.create(number="312", floor=f3)
        cls.r304 = Room.objects.create(number="304", floor=f3)
        cls.r305 = Room.objects.create(number="305", floor=f3)
        cls.ines = make_user("ines", first_name="Inès", last_name="Martin")
        cls.yanis = make_user("yanis", first_name="Yanis", phone="+33611111111")
        cls.awa = make_user("awa", first_name="Awa")  # no device, no phone
        Stay.objects.create(resident=cls.ines, room=cls.r312, arrival=ARRIVAL)
        Stay.objects.create(resident=cls.yanis, room=cls.r304, arrival=ARRIVAL)
        Stay.objects.create(resident=cls.awa, room=cls.r305, arrival=ARRIVAL)
        PushSubscription.objects.create(
            user=cls.ines, endpoint="https://web.push.apple.com/x", p256dh="x", auth="y"
        )

    def setUp(self):
        push = mock.patch("messaging.sending.send_to_user", return_value=PUSHED)
        sms = mock.patch("messaging.sending.send_sms", return_value=SMS_OK)
        self.push = push.start()
        self.sms = sms.start()
        self.addCleanup(mock.patch.stopall)

    def campaign(self, **kwargs):
        data = {
            "title": "Visite le {date}",
            "body": "Bonjour {prénom}, chambre {chambre}.",
            "sms_body": "Bonjour {prénom}, visite chambre {chambre}.",
            "everyone": True,
            "author": self.nadia,
            "event_date": timezone.localdate() + timedelta(days=3),
        }
        data.update(kwargs)
        return Campaign.objects.create(**data)

    def send_now(self, campaign):
        with self.captureOnCommitCallbacks(execute=True):
            sending.schedule(campaign, send_at=timezone.now(), by=self.nadia)
        campaign.refresh_from_db()
        return campaign


class SendNowTests(SendingTestCase):
    def test_push_first_sms_without_device(self):
        campaign = self.send_now(self.campaign())
        self.assertEqual(campaign.status, Campaign.Status.SENT)
        deliveries = {d.recipient: d for d in campaign.deliveries.all()}
        self.assertEqual(deliveries[self.ines].channel, "push")
        self.assertEqual(deliveries[self.ines].status, "sent")
        self.assertEqual(deliveries[self.ines].room_number, "312")
        self.assertTrue(deliveries[self.ines].title.startswith("Visite le "))
        self.assertEqual(deliveries[self.yanis].channel, "sms")
        self.assertEqual(deliveries[self.yanis].provider_message_id, "abc-1")
        self.assertEqual(deliveries[self.yanis].segments, 1)
        self.assertEqual(deliveries[self.awa].status, "failed")
        self.assertEqual(deliveries[self.awa].error, "Ni appareil ni numéro de téléphone.")
        self.push.assert_called_once()
        self.assertEqual(self.push.call_args.args, (self.ines,))
        self.sms.assert_called_once_with("+33611111111", "Bonjour Yanis, visite chambre 304.")
        self.assertTrue(AuditEntry.objects.filter(action=Action.MESSAGE_SCHEDULED).exists())
        entry = AuditEntry.objects.get(action=Action.MESSAGE_SENT)
        self.assertEqual(entry.details["failed"], 1)

    def test_never_twice(self):
        campaign = self.send_now(self.campaign())
        sending.deliver(campaign.pk)  # a second worker, or a resumed run
        Campaign.objects.filter(pk=campaign.pk).update(status=Campaign.Status.SENDING)
        sending.deliver(campaign.pk)
        self.assertEqual(campaign.deliveries.count(), 3)
        self.assertEqual(self.push.call_count, 1)
        self.assertEqual(self.sms.call_count, 1)

    def test_claimed_delivery_is_skipped(self):
        campaign = self.campaign()
        Campaign.objects.filter(pk=campaign.pk).update(
            status=Campaign.Status.SCHEDULED, send_at=timezone.now()
        )
        sending._create_deliveries(campaign, Delivery.Kind.MESSAGE)
        Campaign.objects.filter(pk=campaign.pk).update(
            status=Campaign.Status.SENDING, started_at=timezone.now()
        )
        campaign.deliveries.filter(recipient=self.ines).update(
            status=Delivery.Status.SENDING, claimed_at=timezone.now()
        )
        sending.deliver(campaign.pk)
        self.push.assert_not_called()  # another worker is on it

    def test_no_device_left_falls_back_to_sms(self):
        # All devices answered "gone" (404/410): the SMS takes over.
        self.ines.phone = "+33622222222"
        self.ines.save()
        self.push.return_value = SendResult(removed=1)
        campaign = self.send_now(self.campaign())
        delivery = campaign.deliveries.get(recipient=self.ines)
        self.assertEqual((delivery.channel, delivery.status), ("sms", "sent"))

    def test_push_failing_for_a_while_is_retried_never_a_paid_sms(self):
        # Review of T21: push service down, or a refused key.
        self.ines.phone = "+33622222222"
        self.ines.save()
        self.push.return_value = SendResult(failed=1)
        campaign = self.send_now(self.campaign())
        delivery = campaign.deliveries.get(recipient=self.ines)
        self.assertEqual((delivery.channel, delivery.status), ("push", "pending"))
        self.assertEqual(campaign.status, "sending")
        for minutes in (10, 30):
            later = timezone.now() + timedelta(minutes=minutes)
            with mock.patch("django.utils.timezone.now", return_value=later):
                sending.run_due(later)
        delivery.refresh_from_db()
        self.assertEqual((delivery.channel, delivery.status), ("push", "failed"))
        self.assertNotIn("+33622222222", [c.args[0] for c in self.sms.call_args_list])

    def test_sms_retried_then_sent(self):
        self.sms.side_effect = [SendError("Réseau", temporary=True), SMS_OK]
        campaign = self.send_now(self.campaign())
        delivery = campaign.deliveries.get(recipient=self.yanis)
        self.assertEqual((campaign.status, delivery.status), ("sending", "pending"))
        self.assertEqual(delivery.attempts, 1)
        later = timezone.now() + timedelta(minutes=10)
        with mock.patch("django.utils.timezone.now", return_value=later):
            counts = sending.run_due(later)
        self.assertEqual(counts["resumed"], 1)
        campaign.refresh_from_db()
        delivery.refresh_from_db()
        self.assertEqual((campaign.status, delivery.status), ("sent", "sent"))

    def test_uncertain_sms_is_not_sent_again(self):
        self.sms.side_effect = SendError("Délai dépassé", temporary=True, uncertain=True)
        campaign = self.send_now(self.campaign())
        delivery = campaign.deliveries.get(recipient=self.yanis)
        self.assertEqual(delivery.status, "failed")
        self.assertIn("peut-être parti", delivery.error)
        self.assertEqual(campaign.status, "sent")

    def test_worker_stopped_while_sending(self):
        campaign = self.campaign()
        Campaign.objects.filter(pk=campaign.pk).update(
            status=Campaign.Status.SCHEDULED, send_at=timezone.now()
        )
        sending._create_deliveries(campaign, Delivery.Kind.MESSAGE)
        Campaign.objects.filter(pk=campaign.pk).update(
            status=Campaign.Status.SENDING, started_at=timezone.now() - timedelta(hours=1)
        )
        campaign.deliveries.filter(recipient=self.ines).update(
            status=Delivery.Status.SENDING, claimed_at=timezone.now() - timedelta(hours=1)
        )
        sending.run_due()
        delivery = campaign.deliveries.get(recipient=self.ines)
        self.assertEqual(delivery.status, "failed")
        self.assertIn("état inconnu", delivery.error)
        self.push.assert_not_called()

    def test_one_error_does_not_stop_the_others(self):
        self.push.side_effect = RuntimeError("boom")
        with self.assertLogs("messaging.sending", "ERROR"):
            campaign = self.send_now(self.campaign())
        self.assertEqual(campaign.deliveries.get(recipient=self.yanis).status, "sent")
        self.assertEqual(campaign.status, "sent")


class ScheduleTests(SendingTestCase):
    def test_later(self):
        send_at = timezone.now() + timedelta(hours=2)
        campaign = self.campaign()
        with self.captureOnCommitCallbacks(execute=True):
            sending.schedule(campaign, send_at=send_at, by=self.nadia)
        campaign.refresh_from_db()
        self.assertEqual((campaign.status, campaign.deliveries.count()), ("scheduled", 0))
        self.assertEqual(sending.run_due()["messages"], 0)
        later = send_at + timedelta(minutes=1)
        with mock.patch("django.utils.timezone.now", return_value=later):
            self.assertEqual(sending.run_due(later)["messages"], 1)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, "sent")

    def test_problems(self):
        campaign = self.campaign(everyone=False, body="Le {date} à {début}")
        found = sending.problems(campaign, timezone.now() - timedelta(hours=1))
        self.assertIn(
            "Aucun destinataire : choisissez un étage, une chambre ou une personne.", found
        )
        self.assertIn("Indiquez la valeur de {début}.", found)
        self.assertIn("L'heure d'envoi est passée.", found)
        campaign = self.campaign(remind=True)
        self.assertIn(
            "La relance demande une réponse « Présent » ou « Absent ».",
            sending.problems(campaign, timezone.now()),
        )
        campaign = self.campaign(
            remind=True, reply_type=ReplyType.ATTENDANCE, event_date=timezone.localdate()
        )
        late = at(timezone.localdate(), 9)
        self.assertIn(
            "La relance (le jour J à 8 h) doit venir au moins une heure après l'envoi.",
            sending.problems(campaign, late),
        )
        with self.assertRaises(ValidationError):
            sending.schedule(campaign, send_at=late, by=self.nadia)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, "draft")

    def test_cancel_and_back_to_draft(self):
        campaign = self.campaign()
        send_at = timezone.now() + timedelta(hours=2)
        sending.schedule(campaign, send_at=send_at, by=self.nadia)
        self.assertTrue(sending.cancel(campaign, by=self.nadia, back_to_draft=True))
        campaign.refresh_from_db()
        self.assertEqual((campaign.status, campaign.send_at), ("draft", None))
        sending.schedule(campaign, send_at=send_at, by=self.nadia)
        self.assertTrue(sending.cancel(campaign, by=self.nadia))
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, "cancelled")
        self.assertFalse(sending.cancel(campaign, by=self.nadia))  # already over
        self.assertEqual(AuditEntry.objects.filter(action=Action.MESSAGE_CANCELLED).count(), 2)

    @override_settings(TASKS={"default": {"BACKEND": "django.tasks.backends.dummy.DummyBackend"}})
    def test_task_arguments_are_json(self):
        from django.tasks import default_task_backend

        default_task_backend.clear()
        campaign = self.campaign()
        with self.captureOnCommitCallbacks(execute=True):
            sending.schedule(campaign, send_at=timezone.now(), by=self.nadia)
        (result,) = default_task_backend.results
        self.assertEqual(result.args, [campaign.pk, "message"])
        self.assertEqual(result.task.module_path, "messaging.tasks.deliver_task")


class ReminderTests(SendingTestCase):
    def test_only_those_who_did_not_answer(self):
        event = timezone.localdate() + timedelta(days=3)
        campaign = self.campaign(
            remind=True, reply_type=ReplyType.ATTENDANCE, event_date=event, everyone=False
        )
        campaign.rooms.add(self.r312, self.r304)
        campaign = self.send_now(campaign)
        self.assertEqual(campaign.remind_at, at(event, 8))
        AttendanceReply.objects.create(campaign=campaign, resident=self.ines, answer="present")
        self.assertEqual(sending.run_due()["reminders"], 0)  # not yet
        when = at(event, 8, 1)
        with mock.patch("django.utils.timezone.now", return_value=when):
            self.assertEqual(sending.run_due(when)["reminders"], 1)
            self.assertEqual(sending.run_due(when)["reminders"], 0)  # only once
        reminders = campaign.deliveries.filter(kind=Delivery.Kind.REMINDER)
        self.assertEqual([d.recipient for d in reminders], [self.yanis])
        self.assertTrue(self.sms.call_args.args[1].startswith("Rappel : Bonjour Yanis"))
        self.assertEqual(reminders.get().status, "sent")


class PlannedDepartureTests(SendingTestCase):
    def test_recorded_on_the_day_at_noon(self):
        from residents.departure import plan_departure

        day = timezone.localdate() + timedelta(days=2)
        plan_departure(self.yanis, day, by=self.nadia)
        for hour, recorded in ((11, 0), (12, 1)):
            with mock.patch("django.utils.timezone.now", return_value=at(day, hour)):
                self.assertEqual(sending.record_planned_departures(), recorded)
        self.yanis.refresh_from_db()
        self.assertFalse(self.yanis.is_active)
        self.assertEqual(self.yanis.stays.get().departure, day)

    def test_missed_day_is_caught_up(self):
        from residents.departure import plan_departure

        day = timezone.localdate() + timedelta(days=1)
        plan_departure(self.yanis, day, by=self.nadia)
        later = at(day + timedelta(days=3), 7)
        with mock.patch("django.utils.timezone.now", return_value=later):
            self.assertEqual(sending.record_planned_departures(), 1)
        self.assertEqual(self.yanis.stays.get().departure, day)

    def test_pages(self):
        log_in_verified(self.client, self.nadia)
        day = timezone.localdate() + timedelta(days=10)
        url = reverse("residents:departure", args=[self.yanis.pk])
        response = self.client.post(url, {"departure": day.isoformat()}, follow=True)
        save_page("residents-detail-planned-departure", response)
        self.assertContains(response, "prévu le")
        self.assertContains(response, "Annuler le départ prévu")
        self.yanis.refresh_from_db()
        self.assertTrue(self.yanis.is_active)
        self.assertTrue(AuditEntry.objects.filter(action=Action.DEPARTURE_PLANNED).exists())
        response = self.client.post(
            reverse("residents:cancel_planned_departure", args=[self.yanis.pk]), follow=True
        )
        self.assertContains(response, "Départ prévu annulé.")
        self.assertIsNone(self.yanis.stays.get().planned_departure)


class CommandTests(SendingTestCase):
    def test_run_scheduled(self):
        campaign = self.campaign()
        Campaign.objects.filter(pk=campaign.pk).update(
            status=Campaign.Status.SCHEDULED, send_at=timezone.now()
        )
        out = io.StringIO()
        call_command("run_scheduled", stdout=out)
        self.assertIn("Messages : 1.", out.getvalue())
        out = io.StringIO()
        call_command("run_scheduled", stdout=out)
        self.assertEqual(out.getvalue(), "")  # nothing to do: nothing written


class PagesTests(SendingTestCase):
    def test_review_send_and_track(self):
        log_in_verified(self.client, self.nadia)
        campaign = self.campaign()
        response = self.client.get(reverse("messaging:review", args=[campaign.pk]))
        save_page("messaging-review", response)
        self.assertContains(response, "Envoyer maintenant à 3 résidents")
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("messaging:review", args=[campaign.pk]))
        self.assertRedirects(
            response,
            reverse("messaging:tracking", args=[campaign.pk]),
            fetch_redirect_response=False,
        )
        response = self.client.get(response["Location"])
        save_page("messaging-tracking", response)
        self.assertContains(response, "Envoi en cours.")
        self.assertContains(response, "<h1>Visite le ")
        self.assertContains(response, "Ni appareil ni numéro")
        # A sent message cannot be edited: the composer sends to its tracking page.
        response = self.client.get(reverse("messaging:compose", args=[campaign.pk]))
        self.assertRedirects(response, reverse("messaging:tracking", args=[campaign.pk]))
        response = self.client.get(reverse("messaging:list"))
        save_page("messaging-list-sent", response)
        self.assertContains(response, "Envoyés")

    def test_review_shows_problems(self):
        log_in_verified(self.client, self.nadia)
        campaign = self.campaign(everyone=False)
        response = self.client.post(reverse("messaging:review", args=[campaign.pk]))
        save_page("messaging-review-problems", response)
        self.assertContains(response, "Le message ne peut pas encore partir")
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, "draft")

    def test_scheduled_page_and_cancel(self):
        log_in_verified(self.client, self.nadia)
        campaign = self.campaign(send_at=timezone.now() + timedelta(days=1))
        self.client.post(reverse("messaging:review", args=[campaign.pk]))
        response = self.client.get(reverse("messaging:tracking", args=[campaign.pk]))
        save_page("messaging-tracking-scheduled", response)
        self.assertContains(response, "Envoi programmé le")
        response = self.client.post(
            reverse("messaging:cancel", args=[campaign.pk]), {"to": "draft"}, follow=True
        )
        self.assertRedirects(response, reverse("messaging:compose", args=[campaign.pk]))
        self.assertContains(response, "redevenu un brouillon")

    def test_composer_when_section(self):
        log_in_verified(self.client, self.nadia)
        campaign = self.campaign()
        later = (timezone.localtime() + timedelta(days=1)).replace(second=0, microsecond=0)
        data = {
            "type": "visit",
            "title": "Visite",
            "body": "Bonjour {prénom}",
            "sms_body": "",
            "everyone": "on",
            "when": "later",
            "send_at": "",
            "action": "save",
        }
        response = self.client.post(reverse("messaging:compose", args=[campaign.pk]), data)
        self.assertContains(response, "Indiquez la date et l&#x27;heure de l&#x27;envoi.")
        data["send_at"] = later.strftime("%Y-%m-%dT%H:%M")
        data["action"] = "review"
        response = self.client.post(reverse("messaging:compose", args=[campaign.pk]), data)
        self.assertRedirects(response, reverse("messaging:review", args=[campaign.pk]))
        campaign.refresh_from_db()
        self.assertEqual(campaign.send_at, later)


class ReviewTests(SendingTestCase):
    """Cases found by the independent review of T21."""

    def due_campaign(self, **kwargs):
        campaign = self.campaign(**kwargs)
        Campaign.objects.filter(pk=campaign.pk).update(
            status=Campaign.Status.SCHEDULED, send_at=timezone.now()
        )
        return campaign

    def test_start_and_deliveries_go_together(self):
        campaign = self.due_campaign()
        with (
            mock.patch.object(Delivery.objects, "bulk_create", side_effect=RuntimeError("locked")),
            self.assertRaises(RuntimeError),
        ):
            sending.deliver(campaign.pk)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, "scheduled")  # tried again, never "sent" to nobody

    def test_tasks_do_not_pile_up(self):
        self.due_campaign()
        with mock.patch.object(sending, "_enqueue") as enqueue:
            for minute in range(5):
                now = timezone.now() + timedelta(minutes=minute)
                sending.run_due(now)
        self.assertEqual(enqueue.call_count, 1)

    def test_far_too_late_is_not_sent(self):
        campaign = self.campaign()
        Campaign.objects.filter(pk=campaign.pk).update(
            status=Campaign.Status.SCHEDULED, send_at=timezone.now() - timedelta(hours=13)
        )
        self.assertEqual(sending.run_due()["late"], 1)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, "cancelled")
        self.push.assert_not_called()
        entry = AuditEntry.objects.get(action=Action.MESSAGE_CANCELLED)
        self.assertTrue(entry.details["too_late"])

    def test_reminder_too_late_or_cancelled(self):
        event = timezone.localdate() + timedelta(days=3)
        campaign = self.send_now(
            self.campaign(remind=True, reply_type=ReplyType.ATTENDANCE, event_date=event)
        )
        self.assertTrue(sending.cancel_reminder(campaign, by=self.nadia))
        campaign.refresh_from_db()
        self.assertIsNone(campaign.remind_at)
        campaign = self.send_now(
            self.campaign(remind=True, reply_type=ReplyType.ATTENDANCE, event_date=event)
        )
        noon = at(event, 12, 30)
        with mock.patch("django.utils.timezone.now", return_value=noon):
            counts = sending.run_due(noon)
        self.assertEqual((counts["reminders"], counts["late"]), (0, 1))
        self.assertFalse(campaign.deliveries.filter(kind=Delivery.Kind.REMINDER).exists())

    def test_reminder_uses_the_channel_of_today(self):
        event = timezone.localdate() + timedelta(days=3)
        campaign = self.send_now(
            self.campaign(remind=True, reply_type=ReplyType.ATTENDANCE, event_date=event)
        )
        PushSubscription.objects.create(
            user=self.yanis, endpoint="https://web.push.apple.com/y", p256dh="x", auth="y"
        )
        when = at(event, 8, 1)
        with mock.patch("django.utils.timezone.now", return_value=when):
            sending.run_due(when)
        reminder = campaign.deliveries.get(kind=Delivery.Kind.REMINDER, recipient=self.yanis)
        self.assertEqual(reminder.channel, "push")
        campaign.refresh_from_db()
        self.assertIsNotNone(campaign.reminder_sent_at)

    def test_reminder_prefix_never_costs_one_more_sms(self):
        short = "x" * 100
        self.assertEqual(sending.reminder_sms(short), "Rappel : " + short)
        full = "x" * 155
        self.assertEqual(sending.reminder_sms(full), full)

    def test_sms_not_configured(self):
        with override_settings(SMS={"BACKEND": "sms.providers.disabled.DisabledProvider"}):
            found = sending.problems(self.campaign(), timezone.now())
        self.assertIn("L'envoi de SMS n'est pas configuré", " ".join(found))

    def test_planned_departure_kept_after_a_move(self):
        from housing.services import assign_room
        from residents.departure import plan_departure

        day = timezone.localdate() + timedelta(days=20)
        plan_departure(self.yanis, day, by=self.nadia)
        assign_room(self.yanis, Room.objects.create(number="306", floor=self.f3))
        self.assertEqual(self.yanis.stays.get(departure__isnull=True).planned_departure, day)

    def test_planned_departure_that_cannot_be_recorded_is_dropped(self):
        from residents.departure import plan_departure

        day = timezone.localdate() + timedelta(days=2)
        plan_departure(self.yanis, day, by=self.nadia)
        # The arrival is changed afterwards to a later date.
        self.yanis.stays.update(arrival=day + timedelta(days=1))
        later = at(day + timedelta(days=1), 13)
        with (
            mock.patch("django.utils.timezone.now", return_value=later),
            self.assertLogs("messaging.sending", "WARNING"),
        ):
            self.assertEqual(sending.record_planned_departures(), 0)
        self.assertIsNone(self.yanis.stays.get().planned_departure)
        self.assertTrue(AuditEntry.objects.filter(action=Action.DEPARTURE_PLAN_CANCELLED).exists())

    def test_planned_departure_pages(self):
        from residents.departure import plan_departure

        log_in_verified(self.client, self.nadia)
        url = reverse("residents:departure", args=[self.yanis.pk])
        response = self.client.post(url, {"departure": "2026-08-31"})
        self.assertContains(response, "avant l&#x27;arrivée")
        day = timezone.localdate() + timedelta(days=20)
        plan_departure(self.yanis, day, by=self.nadia)
        response = self.client.get(url)
        save_page("residents-departure-planned", response)
        self.assertContains(response, f'value="{day.isoformat()}"')  # never today by mistake
        self.assertContains(response, "Départ déjà prévu le")

    def test_list_title(self):
        log_in_verified(self.client, self.nadia)
        self.send_now(self.campaign())
        response = self.client.get(reverse("messaging:list"))
        self.assertContains(response, "<title>Messages · HJB Résidence</title>")

    def test_composer_date_without_programmer_and_late_save(self):
        log_in_verified(self.client, self.nadia)
        campaign = self.campaign()
        data = {
            "type": "visit",
            "title": "Visite",
            "body": "Bonjour",
            "everyone": "on",
            "when": "now",
            "send_at": "2026-12-01T10:00",
            "action": "save",
        }
        url = reverse("messaging:compose", args=[campaign.pk])
        self.assertContains(self.client.post(url, data), "Choisissez « Programmer »")
        Campaign.objects.filter(pk=campaign.pk).update(status=Campaign.Status.SCHEDULED)
        data["send_at"] = ""
        response = self.client.post(url, data)
        self.assertRedirects(response, reverse("messaging:tracking", args=[campaign.pk]))
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, "scheduled")
