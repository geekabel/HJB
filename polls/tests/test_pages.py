"""Votes from end to end: composer, sending, voting, reminder, results (card T25)."""

import re
from datetime import date, datetime, time, timedelta
from unittest import mock

from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user
from housing.models import Floor, Room, Stay
from messaging import replies, sending
from messaging.models import Campaign, Delivery, MessageType
from messaging.services import send_test
from push.models import PushSubscription
from push.services import SendResult
from sms.providers.base import SendResult as SmsResult
from tools.html_capture import save_page

from ..models import Option, Participation, Poll
from ..services import set_options

ARRIVAL = date(2026, 9, 1)


class VoteTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.nadia = make_user("nadia", Role.FRONT_DESK, first_name="Nadia")
        floor = Floor.objects.create(number=3)
        cls.people = []
        for number, name in enumerate(("Inès", "Yanis", "Lina", "Omar"), start=1):
            user = make_user(f"r{number}", first_name=name, phone=f"+3361111111{number}")
            Stay.objects.create(
                resident=user,
                room=Room.objects.create(number=f"30{number}", floor=floor),
                arrival=ARRIVAL,
            )
            cls.people.append(user)
        cls.ines, cls.yanis = cls.people[:2]
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

    def sent_vote(self, closes_in=timedelta(days=3), **kwargs):
        campaign = Campaign.objects.create(
            type=MessageType.VOTE,
            title="Soirée de fin d'année : quelle date ?",
            body="Bonjour {prénom}, votez pour la date de la soirée.",
            sms_body="Bonjour {prénom}, quelle date pour la soirée ?",
            everyone=True,
            author=self.nadia,
            **kwargs,
        )
        poll = Poll.objects.create(campaign=campaign, closes_at=timezone.now() + closes_in)
        set_options(poll, ["Vendredi 12 décembre", "Samedi 13 décembre", "Vendredi 19 décembre"])
        with self.captureOnCommitCallbacks(execute=True):
            sending.schedule(campaign, send_at=timezone.now(), by=self.nadia)
        campaign.refresh_from_db()
        return campaign

    def link(self, campaign, user):
        return replies.reply_path(campaign.pk, user.pk)

    def option(self, campaign, position):
        return campaign.poll.options.get(position=position).pk


class ComposerTests(VoteTestCase):
    def post(self, campaign=None, **data):
        url = (
            reverse("messaging:compose", args=[campaign.pk])
            if campaign
            else reverse("messaging:new")
        )
        base = {
            "type": "vote",
            "title": "Quelle date pour la soirée ?",
            "body": "Votez.",
            "everyone": "on",
            "when": "now",
            "poll-options": "Vendredi 12\nSamedi 13\n\nsamedi 13\nVendredi 19",
            "poll-closes_at": (timezone.localtime() + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M"),
            "poll-allow_comment": "on",
            "action": "save",
        }
        return self.client.post(url, base | data)

    def test_vote_draft(self):
        log_in_verified(self.client, self.nadia)
        self.post()
        campaign = Campaign.objects.get()
        poll = campaign.poll
        self.assertEqual(
            list(poll.options.values_list("label", flat=True)),
            ["Vendredi 12", "Samedi 13", "Vendredi 19"],
        )
        self.assertTrue(poll.allow_comment)
        response = self.client.get(reverse("messaging:compose", args=[campaign.pk]))
        save_page("polls-compose", response)
        self.assertContains(response, "Vendredi 12\nSamedi 13\nVendredi 19</textarea>")
        response = self.client.get(reverse("messaging:review", args=[campaign.pk]))
        save_page("polls-review", response)
        self.assertContains(response, "Vendredi 12 · Samedi 13 · Vendredi 19")
        # Another type: the poll stays in the draft (a wrong click loses nothing)...
        self.post(campaign, type="announcement")
        self.assertTrue(Poll.objects.exists())
        # ...and goes away when the message leaves.
        with self.captureOnCommitCallbacks(execute=True):
            sending.schedule(Campaign.objects.get(), send_at=timezone.now(), by=self.nadia)
        self.assertFalse(Poll.objects.exists())

    def test_incomplete_draft_is_saved(self):
        log_in_verified(self.client, self.nadia)
        self.post(**{"poll-options": "Un seul", "poll-closes_at": ""})
        campaign = Campaign.objects.get()
        self.assertEqual(campaign.poll.options.count(), 1)
        self.post(
            campaign, action="add", add="301", **{"poll-options": "Un seul", "poll-closes_at": ""}
        )
        self.assertEqual(list(campaign.rooms.values_list("number", flat=True)), ["301"])
        response = self.client.get(reverse("messaging:review", args=[campaign.pk]))
        self.assertContains(response, "Proposez au moins 2 choix pour le vote.")
        self.assertContains(response, "Indiquez la date et l&#x27;heure de clôture du vote.")

    def test_composer_errors(self):
        log_in_verified(self.client, self.nadia)
        response = self.post(**{"poll-options": "\n".join("ABCDEFG")})
        self.assertContains(response, "6 choix au plus.")
        self.assertContains(response, "Corrigez le champ signalé ci-dessous.")
        self.assertFalse(Campaign.objects.exists())
        response = self.post(title="", **{"poll-options": "\n".join("ABCDEFG")})
        self.assertContains(response, "Corrigez les champs signalés ci-dessous.")
        response = self.post(ask_reply="on")
        self.assertContains(
            response, "Un vote ne demande pas « Présent » ou « Absent » : décochez."
        )
        # The reminder is allowed for a vote.
        self.post(remind="on")
        self.assertTrue(Campaign.objects.get().remind)

    def test_problems_before_sending(self):
        campaign = Campaign.objects.create(
            type=MessageType.VOTE,
            title="Q",
            body="B",
            everyone=True,
            author=self.nadia,
            remind=True,
        )
        now = timezone.now()
        found = sending.problems(campaign, now)
        self.assertIn("Proposez au moins 2 choix pour le vote.", found)
        self.assertIn("Indiquez la date et l'heure de clôture du vote.", found)
        poll = Poll.objects.create(campaign=campaign, closes_at=now + timedelta(minutes=30))
        set_options(poll, ["A", "B"])
        campaign.refresh_from_db()
        self.assertIn(
            "La clôture du vote doit venir au moins une heure après l'envoi.",
            sending.problems(campaign, now),
        )
        Poll.objects.filter(pk=poll.pk).update(closes_at=now + timedelta(hours=10))
        campaign.refresh_from_db()
        self.assertTrue(
            any(
                p.startswith("La relance (24 h avant la clôture)")
                for p in sending.problems(campaign, now)
            )
        )
        Poll.objects.filter(pk=poll.pk).update(closes_at=now + timedelta(days=2))
        campaign.refresh_from_db()
        self.assertEqual(sending.problems(campaign, now), [])


class SendingTests(VoteTestCase):
    def test_sms_has_the_vote_link_and_no_answer_buttons(self):
        campaign = self.sent_vote()
        texts = [c.args[1] for c in self.sms.call_args_list]
        expected = "http://localhost:8000" + self.link(campaign, self.yanis)
        self.assertIn(f"Bonjour Yanis, quelle date pour la soirée ? Votez ici : {expected}", texts)
        self.assertEqual(self.push.call_args.kwargs["reply"], "")  # no Présent/Absent buttons
        self.assertEqual(
            self.push.call_args.kwargs["url"], reverse("inbox:message", args=[campaign.pk])
        )

    def test_reminder_only_to_those_who_did_not_vote(self):
        campaign = self.sent_vote(closes_in=timedelta(days=3), remind=True)
        self.assertEqual(campaign.remind_at, sending.reminder_time(campaign))
        self.assertLessEqual(campaign.remind_at, campaign.poll.closes_at - timedelta(hours=24))
        Client().post(self.link(campaign, self.yanis), {"option": self.option(campaign, 1)})
        log_in_verified(self.client, self.ines)
        self.client.post(
            reverse("inbox:message", args=[campaign.pk]), {"option": self.option(campaign, 2)}
        )
        with mock.patch("django.utils.timezone.now", return_value=campaign.remind_at):
            sending.run_due(campaign.remind_at)
        reminded = campaign.deliveries.filter(kind=Delivery.Kind.REMINDER)
        self.assertEqual(sorted(d.recipient.first_name for d in reminded), ["Lina", "Omar"])


class VotePageTests(VoteTestCase):
    def test_vote_by_link(self):
        campaign = self.sent_vote()
        client = Client(enforce_csrf_checks=True)  # no session: the link is the proof
        url = self.link(campaign, self.yanis)
        response = client.get(url)
        save_page("polls-vote-link", response)
        self.assertContains(response, "Un seul choix. Vote anonyme.")
        self.assertContains(
            response,
            '<legend class="vote__question">Soirée de fin d&#x27;année : quelle date ?</legend>',
        )
        self.assertContains(response, 'autocomplete="off"')
        self.assertContains(response, "Samedi 13 décembre")
        self.assertFalse(Participation.objects.exists())  # a preview never votes
        self.assertIsNone(campaign.deliveries.get(recipient=self.yanis).read_at)
        response = client.post(
            url, {"option": self.option(campaign, 2), "comment": "Cuisine du monde ?"}
        )
        save_page("polls-vote-link-done", response)
        self.assertContains(response, "Merci, votre vote est enregistré. Il reste anonyme.")
        self.assertNotContains(response, "Envoyer mon vote")
        self.assertEqual(campaign.poll.options.get(position=2).votes, 1)
        read_at = campaign.deliveries.get(recipient=self.yanis).read_at
        self.assertEqual(timezone.localtime(read_at).time(), time(0, 0))  # the day, not the time
        response = client.post(url, {"option": self.option(campaign, 1), "comment": "gardé"})
        self.assertContains(
            response, "Vous avez déjà voté. Un seul vote par personne.", status_code=400
        )
        self.assertNotContains(response, "gardé", status_code=400)  # voted: no form any more
        response = client.post(self.link(campaign, self.people[2]), {"comment": "mon avis"})
        self.assertContains(response, ">mon avis</textarea>", status_code=400)  # comment kept
        response = client.post(self.link(campaign, self.people[2]), {"option": "999"})
        self.assertContains(response, "Choisissez une des réponses proposées.", status_code=400)

    def test_closed(self):
        campaign = self.sent_vote()
        Poll.objects.filter(campaign=campaign).update(closes_at=timezone.now())
        url = self.link(campaign, self.yanis)
        self.assertContains(self.client.get(url), "Le vote est clos.")
        response = self.client.post(url, {"option": self.option(campaign, 1)})
        self.assertEqual(response.status_code, 409)
        self.assertFalse(Participation.objects.exists())

    def test_vote_in_the_app_and_inbox(self):
        campaign = self.sent_vote()
        log_in_verified(self.client, self.ines)
        inbox = self.client.get(reverse("inbox:list"))
        self.assertContains(inbox, "À répondre</span>")
        self.assertContains(inbox, "Vote · clôture le ")
        url = reverse("inbox:message", args=[campaign.pk])
        response = self.client.get(url)
        save_page("polls-vote-app", response)
        self.assertContains(response, "Un commentaire pour l'équipe (facultatif)")
        response = self.client.post(url, {"option": self.option(campaign, 3)}, follow=True)
        save_page("polls-vote-app-done", response)
        self.assertContains(response, "Merci, votre vote est enregistré. Il reste anonyme.")
        self.assertContains(response, "Vous avez voté.")
        self.assertContains(self.client.get(reverse("inbox:list")), "A voté</span>")
        response = self.client.post(url, {"option": self.option(campaign, 1)})
        self.assertContains(response, "Vous avez déjà voté.", status_code=400)
        Poll.objects.filter(campaign=campaign).update(closes_at=timezone.now())
        self.assertContains(self.client.get(reverse("inbox:list")), "Vote · vote clos")
        self.assertEqual([o.votes for o in campaign.poll.options.all()], [0, 0, 1])


class ResultsTests(VoteTestCase):
    def test_hidden_before_closing_then_shown(self):
        campaign = self.sent_vote()
        for person, position in zip(self.people[:3], (2, 2, 1), strict=True):
            Client().post(
                self.link(campaign, person),
                {
                    "option": self.option(campaign, position),
                    "comment": f"avis de {person.first_name}",
                },
            )
        log_in_verified(self.client, self.nadia)
        url = reverse("messaging:tracking", args=[campaign.pk])
        response = self.client.get(url)
        save_page("polls-results-before", response)
        self.assertContains(
            response, "Les résultats et les commentaires s'affichent après la clôture."
        )
        self.assertNotContains(response, "avis de")
        self.assertContains(response, '<span class="badge badge--success">A voté</span>', count=3)
        Poll.objects.filter(campaign=campaign).update(closes_at=timezone.now())
        response = self.client.get(url)
        save_page("polls-results", response)
        self.assertContains(response, "<strong>2 voix · 67 %</strong>")
        self.assertContains(response, "Commentaires (3)")
        self.assertContains(response, "avis de Inès")

    def test_too_few_voters(self):
        campaign = self.sent_vote()
        Client().post(self.link(campaign, self.yanis), {"option": self.option(campaign, 1)})
        log_in_verified(self.client, self.nadia)
        Poll.objects.filter(campaign=campaign).update(closes_at=timezone.now())
        response = self.client.get(reverse("messaging:tracking", args=[campaign.pk]))
        self.assertContains(response, "Moins de 3 votants : les résultats ne sont pas affichés")
        self.assertNotContains(response, "voix ·")


class SafetyTests(VoteTestCase):
    def test_previews_and_tests_never_hold_a_working_link(self):
        """No staff member can answer or vote in a resident's name (review of T25)."""
        log_in_verified(self.client, self.nadia)
        for kind in ("vote", "attendance"):
            campaign = Campaign.objects.create(
                type=MessageType.VOTE if kind == "vote" else MessageType.VISIT,
                reply_type="attendance" if kind == "attendance" else "none",
                title="Q",
                body="B",
                everyone=True,
                author=self.nadia,
            )
            if kind == "vote":
                poll = Poll.objects.create(
                    campaign=campaign, closes_at=timezone.now() + timedelta(days=2)
                )
                set_options(poll, ["A", "B"])
            page = self.client.get(
                reverse("messaging:compose", args=[campaign.pk])
            ).content.decode()
            tokens = re.findall(r"/r/([^/\s<]+)/", page)
            self.assertTrue(tokens, kind)
            self.assertTrue(all(replies.read_token(t) is None for t in tokens), kind)
            # The test SMS to the staff phone: the same harmless link.
            self.nadia.phone = "+33622222222"
            self.nadia.save()
            with mock.patch("messaging.services.send_sms") as test_sms:
                send_test(campaign, self.nadia, by_sms=True)
            token = re.search(r"/r/([^/\s]+)/", test_sms.call_args.args[1]).group(1)
            self.assertIsNone(replies.read_token(token), kind)

    def test_reminder_never_at_night(self):
        campaign = self.sent_vote(closes_in=timedelta(days=4), remind=True)
        paris = timezone.get_current_timezone()
        for closing, expected in (
            (datetime(2026, 12, 12, 2, 0), datetime(2026, 12, 10, 20, 0)),  # 2:00 the day before
            (datetime(2026, 12, 12, 23, 0), datetime(2026, 12, 11, 20, 0)),
            (datetime(2026, 12, 12, 15, 0), datetime(2026, 12, 11, 15, 0)),
        ):
            Poll.objects.filter(campaign=campaign).update(closes_at=closing.replace(tzinfo=paris))
            campaign.refresh_from_db()
            self.assertEqual(sending.reminder_time(campaign), expected.replace(tzinfo=paris))

    def test_late_vote_is_cancelled_not_sent(self):
        campaign = Campaign.objects.create(
            type=MessageType.VOTE, title="Q", body="B", everyone=True, author=self.nadia
        )
        poll = Poll.objects.create(campaign=campaign, closes_at=timezone.now() + timedelta(days=1))
        set_options(poll, ["A", "B"])
        sending.schedule(campaign, send_at=timezone.now() + timedelta(hours=1), by=self.nadia)
        later = timezone.now() + timedelta(days=2)  # the worker was stopped
        with mock.patch("django.utils.timezone.now", return_value=later):
            sending.deliver(campaign.pk)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, Campaign.Status.CANCELLED)
        self.assertFalse(campaign.deliveries.exists())

    def test_vote_writes_every_option_row(self):
        campaign = self.sent_vote()
        with CaptureQueriesContext(connection) as queries:
            Client().post(self.link(campaign, self.yanis), {"option": self.option(campaign, 2)})
        updates = [q["sql"] for q in queries if q["sql"].startswith('UPDATE "polls_option"')]
        self.assertEqual(len(updates), 1)
        self.assertNotIn('"polls_option"."id" =', updates[0].split("WHERE")[1])  # all rows
        self.assertTrue(any(q["sql"].startswith('UPDATE "polls_poll"') for q in queries))

    def test_options_frozen_after_votes(self):
        campaign = self.sent_vote()
        Client().post(self.link(campaign, self.yanis), {"option": self.option(campaign, 1)})
        with self.assertRaises(ValueError):
            set_options(campaign.poll, ["X", "Y"])

    def test_not_in_the_admin(self):
        from django.contrib import admin

        for model in (Poll, Option, Participation):
            self.assertNotIn(model, admin.site._registry)

    def test_link_of_a_cancelled_vote(self):
        campaign = self.sent_vote()
        Campaign.objects.filter(pk=campaign.pk).update(status=Campaign.Status.CANCELLED)
        response = self.client.post(
            self.link(campaign, self.yanis), {"option": self.option(campaign, 1)}
        )
        self.assertEqual(response.status_code, 409)
        self.assertFalse(Participation.objects.exists())
