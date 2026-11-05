"""Vote, close and count (card T25). See models.py for anonymity."""

import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from .models import Option, Participation, Poll

MIN_OPTIONS = 2
MAX_OPTIONS = 6
MAX_COMMENT = 500
# Fewer voters: the results could show what someone chose.
MIN_VOTERS_FOR_RESULTS = 3
# The reminder of the people who did not vote, before the closing.
REMINDER_BEFORE_CLOSING = timedelta(hours=24)


class VoteRefused(Exception):
    """French message for the resident."""


def poll_of(campaign):
    """The poll of a message, or None."""
    if campaign is None or not campaign.pk:
        return None
    try:
        return campaign.poll
    except Poll.DoesNotExist:
        return None


def is_open(poll, now=None):
    from messaging.models import Campaign

    return (
        poll.closes_at is not None
        and poll.campaign.status in (Campaign.Status.SENDING, Campaign.Status.SENT)
        and (now or timezone.now()) < poll.closes_at
    )


def is_closed(poll, now=None):
    """The closing time has passed (the results can be shown)."""
    return poll.closes_at is not None and (now or timezone.now()) >= poll.closes_at


def has_voted(poll, user):
    return Participation.objects.filter(poll=poll, resident=user).exists()


def set_options(poll, labels):
    """Replace the options of a poll that was not sent yet."""
    labels = clean_labels(labels)
    with transaction.atomic():
        poll.options.all().delete()
        Option.objects.bulk_create(
            Option(poll=poll, label=label, position=number)
            for number, label in enumerate(labels, start=1)
        )


def clean_labels(labels):
    """One option per line: no empty line, no repeat, 80 characters at most."""
    seen, kept = set(), []
    for label in labels:
        label = " ".join(label.split())[:80]
        if label and label.casefold() not in seen:
            seen.add(label.casefold())
            kept.append(label)
    return kept


def vote(poll, user, option_id, comment=""):
    """Record the vote of ``user``. Raise VoteRefused (French message) if refused."""
    comment = (comment or "").strip()[:MAX_COMMENT]
    with transaction.atomic():
        # Lock the poll: the comments are a list read then written.
        poll = Poll.objects.select_for_update().select_related("campaign").get(pk=poll.pk)
        if not is_open(poll):
            raise VoteRefused("Le vote est clos.")
        try:
            option_id = int(option_id)
        except (TypeError, ValueError):
            option_id = 0
        if not poll.options.filter(pk=option_id).exists():
            raise VoteRefused("Choisissez une des réponses proposées.")
        try:
            with transaction.atomic():
                Participation.objects.create(
                    poll=poll, resident=user, voted_on=timezone.localdate()
                )
        except IntegrityError:
            raise VoteRefused("Vous avez déjà voté. Un seul vote par personne.") from None
        Option.objects.filter(pk=option_id).update(votes=F("votes") + 1)
        if comment and poll.allow_comment:
            # At a random place: the order of the list says nothing.
            poll.comments.insert(secrets.randbelow(len(poll.comments) + 1), comment)
            poll.save(update_fields=["comments"])


@dataclass
class Results:
    voters: int
    shown: bool  # closed, and enough voters
    options: list  # (label, votes, percent)
    comments: list


def results(poll, now=None):
    voters = poll.participations.count()
    shown = is_closed(poll, now) and voters >= MIN_VOTERS_FOR_RESULTS
    options, comments = [], []
    if shown:
        total = sum(option.votes for option in poll.options.all()) or 1
        options = [
            (option.label, option.votes, round(100 * option.votes / total))
            for option in poll.options.all()
        ]
        comments = list(Poll.objects.values_list("comments", flat=True).get(pk=poll.pk))
        secrets.SystemRandom().shuffle(comments)
    return Results(voters, shown, options, comments)
