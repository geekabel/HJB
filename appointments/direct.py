"""Direct messages between a resident and an educator (card T28).

A resident writes to an educator (any active educator); the educator answers
in the same conversation. Each side sees what is unread. The other person gets
a notification that says who wrote, never the text: a notification can show on
a locked screen.
"""

from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from accounts.roles import GROUP_BY_ROLE, Role

from .models import Conversation, DirectMessage

MAX_LENGTH = 2000
MAX_PER_DAY = 30  # messages one person sends in one conversation, in 24 hours


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


def send(conversation_or_none, author, text, *, resident=None, educator=None):
    """Save the message and notify the other person. Return the DirectMessage.

    A first message creates the conversation (``resident`` and ``educator``).
    """
    text = (text or "").strip()
    if not text:
        raise MessageRefused("Écrivez un message avant d'envoyer.")
    if len(text) > MAX_LENGTH:
        raise MessageRefused(f"Le message est trop long ({MAX_LENGTH} caractères au plus).")
    with transaction.atomic():
        conversation = conversation_or_none
        if conversation is None:
            conversation, _ = Conversation.objects.get_or_create(
                resident=resident, educator=educator
            )
        conversation = Conversation.objects.select_for_update().get(pk=conversation.pk)
        since = timezone.now() - timedelta(days=1)
        if conversation.messages.filter(author=author, sent_at__gte=since).count() >= MAX_PER_DAY:
            raise MessageRefused(
                "Vous avez envoyé beaucoup de messages aujourd'hui. Réessayez demain, "
                "ou passez à l'accueil."
            )
        message = DirectMessage.objects.create(conversation=conversation, author=author, text=text)
        Conversation.objects.filter(pk=conversation.pk).update(updated_at=message.sent_at)
        other = conversation.educator if author == conversation.resident else conversation.resident
        transaction.on_commit(lambda: _notify(conversation, author, other))
    return message


def _notify(conversation, author, other):
    from .tasks import notify_task

    if other == conversation.educator:
        url = reverse("appointments:conversation", args=[conversation.pk])
    else:
        url = reverse("rdv:write", args=[conversation.educator_id])
    notify_task.enqueue(
        user_id=other.pk,
        title="Nouveau message",
        body=f"{first_name(author)} vous a écrit.",
        url=url,
        tag=f"conversation-{conversation.pk}",
    )


def mark_read(conversation, reader):
    """The messages of the other person, now read by ``reader``."""
    return (
        conversation.messages.exclude(author=reader)
        .filter(read_at__isnull=True)
        .update(read_at=timezone.now())
    )


def with_unread(conversations, reader):
    """Annotate each conversation with ``unread``: messages from the other person."""
    return conversations.annotate(
        unread=Count(
            "messages",
            filter=Q(messages__read_at__isnull=True) & ~Q(messages__author=reader),
        )
    )


def unread_count(user):
    """Unread direct messages of ``user``, as a resident or as an educator."""
    if not user.is_authenticated:
        return 0
    return (
        DirectMessage.objects.filter(
            Q(conversation__resident=user) | Q(conversation__educator=user),
            read_at__isnull=True,
        )
        .exclude(author=user)
        .count()
    )
