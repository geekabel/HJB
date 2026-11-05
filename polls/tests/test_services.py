"""Anonymous polls: vote, close, count (card T25)."""

from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from accounts.roles import Role
from accounts.tests.helpers import make_user
from messaging.models import Campaign, MessageType

from .. import services
from ..models import Option, Participation, Poll


def make_poll(author, labels=("Vendredi 12", "Samedi 13", "Vendredi 19"), **kwargs):
    campaign = Campaign.objects.create(
        type=MessageType.VOTE,
        title="Soirée de fin d'année : quelle date ?",
        body="Votez avant vendredi.",
        everyone=True,
        author=author,
        status=Campaign.Status.SENT,
        started_at=timezone.now(),
    )
    poll = Poll.objects.create(
        campaign=campaign, closes_at=timezone.now() + timedelta(days=2), **kwargs
    )
    services.set_options(poll, labels)
    return poll


class VoteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.nadia = make_user("nadia", Role.FRONT_DESK)
        cls.people = [make_user(f"r{n}") for n in range(4)]

    def option(self, poll, position):
        return poll.options.get(position=position)

    def test_vote_counts_without_saying_who(self):
        poll = make_poll(self.nadia)
        services.vote(
            poll, self.people[0], self.option(poll, 2).pk, "Une soirée cuisine du monde ?"
        )
        services.vote(poll, self.people[1], self.option(poll, 2).pk)
        services.vote(poll, self.people[2], self.option(poll, 1).pk, "  ")
        self.assertEqual([o.votes for o in poll.options.all()], [1, 2, 0])
        participation = Participation.objects.get(poll=poll, resident=self.people[0])
        self.assertEqual(participation.voted_on, timezone.localdate())  # the day, not the time
        poll.refresh_from_db()
        self.assertEqual(poll.comments, ["Une soirée cuisine du monde ?"])
        # Nothing links a person to an option: no foreign key from the participation.
        fields = {f.name for f in Participation._meta.get_fields()}
        self.assertEqual(fields, {"id", "poll", "resident", "voted_on"})
        self.assertTrue(services.has_voted(poll, self.people[0]))
        self.assertFalse(services.has_voted(poll, self.people[3]))

    def test_refused(self):
        poll = make_poll(self.nadia)
        other = make_poll(self.nadia)
        services.vote(poll, self.people[0], self.option(poll, 1).pk)
        cases = [
            (
                self.people[0],
                self.option(poll, 2).pk,
                "Vous avez déjà voté. Un seul vote par personne.",
            ),
            (self.people[1], self.option(other, 1).pk, "Choisissez une des réponses proposées."),
            (self.people[1], "abc", "Choisissez une des réponses proposées."),
            (self.people[1], None, "Choisissez une des réponses proposées."),
        ]
        for user, option_id, message in cases:
            with self.assertRaisesMessage(services.VoteRefused, message):
                services.vote(poll, user, option_id)
        self.assertEqual(sum(o.votes for o in poll.options.all()), 1)
        Poll.objects.filter(pk=poll.pk).update(closes_at=timezone.now() - timedelta(minutes=1))
        with self.assertRaisesMessage(services.VoteRefused, "Le vote est clos."):
            services.vote(poll, self.people[1], self.option(poll, 1).pk)
        Campaign.objects.filter(pk=other.campaign_id).update(status=Campaign.Status.DRAFT)
        with self.assertRaisesMessage(services.VoteRefused, "Le vote est clos."):
            services.vote(other, self.people[1], self.option(other, 1).pk)

    def test_comments_off_or_too_long(self):
        poll = make_poll(self.nadia, allow_comment=False)
        services.vote(poll, self.people[0], self.option(poll, 1).pk, "Mon avis")
        poll.refresh_from_db()
        self.assertEqual(poll.comments, [])
        poll = make_poll(self.nadia)
        services.vote(poll, self.people[0], self.option(poll, 1).pk, "x" * 900)
        poll.refresh_from_db()
        self.assertEqual(len(poll.comments[0]), services.MAX_COMMENT)

    def test_comments_at_a_random_place(self):
        poll = make_poll(self.nadia)
        with mock.patch("polls.services.secrets.randbelow", return_value=0):
            services.vote(poll, self.people[0], self.option(poll, 1).pk, "premier")
            services.vote(poll, self.people[1], self.option(poll, 1).pk, "deuxième")
        poll.refresh_from_db()
        self.assertEqual(poll.comments, ["deuxième", "premier"])  # not the order of the votes

    def test_results_only_after_closing_and_with_enough_voters(self):
        poll = make_poll(self.nadia)
        for person, position in zip(self.people[:3], (2, 2, 1), strict=True):
            services.vote(poll, person, self.option(poll, position).pk, f"avis {position}")
        before = services.results(poll)
        self.assertEqual(
            (before.voters, before.shown, before.options, before.comments), (3, False, [], [])
        )
        after = services.results(poll, now=poll.closes_at)
        self.assertTrue(after.shown)
        self.assertEqual(
            after.options, [("Vendredi 12", 1, 33), ("Samedi 13", 2, 67), ("Vendredi 19", 0, 0)]
        )
        self.assertEqual(sorted(after.comments), ["avis 1", "avis 2", "avis 2"])
        small = make_poll(self.nadia)
        services.vote(small, self.people[0], self.option(small, 1).pk)
        self.assertFalse(services.results(small, now=small.closes_at).shown)

    def test_options_cleaned(self):
        self.assertEqual(
            services.clean_labels(["  Vendredi  12 ", "", "vendredi 12", "Samedi", "x" * 100]),
            ["Vendredi 12", "Samedi", "x" * 80],
        )
        poll = make_poll(self.nadia, labels=["A", "B"])
        services.set_options(poll, ["C", "D", "E"])
        self.assertEqual(
            list(poll.options.values_list("label", "position")), [("C", 1), ("D", 2), ("E", 3)]
        )
        self.assertEqual(Option.objects.filter(poll=poll).count(), 3)
