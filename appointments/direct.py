"""Direct messages between a resident and an educator (card T28).

A resident writes to an educator (any active educator); the educator answers
in the same conversation. Each side sees what is unread. The other person gets
a notification that says who wrote, never the text: a notification can show on
a locked screen. The background task only receives the message id: no name is
stored in the task queue (its rows show in the admin site).
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from access.session_policy import is_resident
from accounts.models import User
from accounts.roles import GROUP_BY_ROLE, Role

from .models import Conversation, DirectMessage

MAX_LENGTH = 2000
MAX_PER_DAY = 30  # messages one person sends in one conversation, in 24 hours
MAX_PER_DAY_IN_ALL = 60  # the same, across all conversations of that person
PAGE = 50  # messages shown at once; older ones one page at a time
MANY_NEWLINES = re.compile(r"\n{3,}")


class MessageRefused(Exception):
    """French message for the author."""


def educators():
    """Every active educator, even without open times."""
    return User.objects.filter(is_active=True, groups__name=GROUP_BY_ROLE[Role.EDUCATOR]).order_by(
        "first_name", "last_name"
    )


def first_name(user):
    return user.first_name or user.get_username()


def conversation_of(resident, educator):
    return Conversation.objects.filter(resident=resident, educator=educator).first()


def resident_conversations(resident):
    """The conversations a resident can still open: with an active educator."""
    return Conversation.objects.filter(resident=resident, educator__in=educators())


def clean(text):
    """The text as saved: one kind of line break, no invisible-only message."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if "\x00" in text:
        raise MessageRefused("Le message contient un caractère interdit.")
    text = MANY_NEWLINES.sub("\n\n", text).strip()
    visible = "".join(c for c in text if unicodedata.category(c) != "Cf").strip()
    if not visible:
        raise MessageRefused("Écrivez un message avant d'envoyer.")
    if len(text) > MAX_LENGTH:
        raise MessageRefused("Le message est trop long (2 000 caractères au plus).")
    return text


def send(conversation_or_none, author, text, *, resident=None, educator=None):
    """Save the message and notify the other person. Return the DirectMessage.

    A first message creates the conversation (``resident`` and ``educator``).
    """
    text = clean(text)
    with transaction.atomic():
        conversation = conversation_or_none
        if conversation is None:
            conversation, _ = Conversation.objects.get_or_create(
                resident=resident, educator=educator
            )
        conversation = (
            Conversation.objects.select_for_update()
            .select_related("resident", "educator")
            .get(pk=conversation.pk)
        )
        if author.pk not in (conversation.resident_id, conversation.educator_id):
            raise MessageRefused("Vous ne faites pas partie de cette conversation.")
        other = (
            conversation.educator
            if author.pk == conversation.resident_id
            else conversation.resident
        )
        if not other.is_active:
            raise MessageRefused(
                f"{first_name(other)} n'a plus de compte actif : le message ne serait pas lu."
            )
        since = timezone.now() - timedelta(days=1)
        mine = DirectMessage.objects.filter(author=author, sent_at__gte=since)
        if (
            mine.filter(conversation=conversation).count() >= MAX_PER_DAY
            or mine.count() >= MAX_PER_DAY_IN_ALL
        ):
            raise MessageRefused(
                "Vous avez envoyé beaucoup de messages aujourd'hui. Réessayez demain, "
                "ou passez à l'accueil."
            )
        # One notification until the other person reads: no flood of them.
        already_waiting = conversation.messages.filter(author=author, read_at__isnull=True).exists()
        message = DirectMessage.objects.create(conversation=conversation, author=author, text=text)
        Conversation.objects.filter(pk=conversation.pk).update(updated_at=message.sent_at)
        if not already_waiting:
            # robust: a queue failure never turns a saved message into an error page.
            transaction.on_commit(lambda: _notify(message.pk), robust=True)
    return message


def _notify(message_id):
    from .tasks import notify_message_task

    notify_message_task.enqueue(message_id=message_id)


@dataclass
class Page:
    messages: list
    older: int | None  # pk to ask for the page before, or None
    latest: bool  # the page ends with the last message


def page_of(conversation, before=None):
    """The last PAGE messages, or the PAGE before message ``before``.

    One query that stops at PAGE + 1 rows, on the index (conversation, id):
    as fast with ten years of messages as with ten. ``before`` is a cursor
    (a message id), not a page number, so a new message never shifts it.
    """
    if conversation is None:
        return Page([], None, True)
    query = conversation.messages.select_related("author").order_by("-pk")
    if before is not None:
        query = query.filter(pk__lt=before)
    found = list(query[: PAGE + 1])
    older = found[PAGE - 1].pk if len(found) > PAGE else None
    return Page(list(reversed(found[:PAGE])), older, before is None)


def newer_than(conversation, after):
    """Messages after message ``after`` (a pk), oldest first, at most PAGE.

    For the conversation page that stays open (thread.js asks every few
    seconds): one query on the index (conversation, id). Each message gets
    ``new_day``: True when its day differs from the one before.
    """
    found = list(
        conversation.messages.select_related("author").filter(pk__gt=after).order_by("pk")[:PAGE]
    )
    if found:
        before = conversation.messages.filter(pk=after).values_list("sent_at", flat=True).first()
        day = timezone.localdate(before) if before else None
        for message in found:
            message_day = timezone.localdate(message.sent_at)
            message.new_day = message_day != day
            day = message_day
    return found


def after_id(request):
    """The ?apres= of the URL, or None if absent or wrong."""
    value = request.GET.get("apres", "")
    return int(value) if value.isascii() and value.isdigit() and len(value) < 12 else None


def cursor(request):
    """The ?avant= of the URL, or None if absent or wrong."""
    value = request.GET.get("avant", "")
    return int(value) if value.isascii() and value.isdigit() and len(value) < 12 else None


def mark_read(conversation, reader, among=None):
    """The messages of the other person, now read by ``reader``. Return their ids.

    ``among``: only these messages (the ones just shown), not one that
    arrived meanwhile and is not on screen yet.
    """
    unread = conversation.messages.exclude(author=reader).filter(read_at__isnull=True)
    if among is not None:
        unread = unread.filter(pk__in=[message.pk for message in among])
    ids = list(unread.values_list("pk", flat=True))
    unread.update(read_at=timezone.now())
    return ids


def with_unread(conversations, reader):
    """Annotate each conversation with ``unread``: messages from the other person."""
    return conversations.annotate(
        unread=Count(
            "messages",
            filter=Q(messages__read_at__isnull=True) & ~Q(messages__author=reader),
        )
    )


def unread_count(user):
    """Unread direct messages of ``user``: as a resident, or as an educator."""
    if not user.is_authenticated:
        return 0
    if is_resident(user):
        conversations = resident_conversations(user)
    else:
        conversations = Conversation.objects.filter(educator=user)
    return (
        DirectMessage.objects.filter(conversation__in=conversations, read_at__isnull=True)
        .exclude(author=user)
        .count()
    )
