"""Background tasks of the appointments (cards T28, T29).

Docs: https://docs.djangoproject.com/en/6.1/topics/tasks/
Arguments are ids only: the task rows show in the admin site, and must not
tell who writes to or meets whom.
"""

import logging

from django.core.exceptions import ImproperlyConfigured
from django.tasks import task
from django.urls import reverse

from push.services import send_to_user

from .models import DirectMessage

logger = logging.getLogger(__name__)


def push(user, *, title, body, url, tag):
    """A notification on the devices of the person (best effort). Return the SendResult."""
    if user is None or not user.is_active:
        return None
    try:
        return send_to_user(user, title=title, body=body, url=url, tag=tag)
    except ImproperlyConfigured:
        logger.warning("Notification not sent: push is not configured")
        return None


@task
def notify_message_task(message_id):
    """Tell the other person of a direct message: who wrote, never the text."""
    message = (
        DirectMessage.objects.filter(pk=message_id)
        .select_related("conversation__resident", "conversation__educator", "author")
        .first()
    )
    if message is None:
        return
    conversation = message.conversation
    if message.author_id == conversation.resident_id:
        other = conversation.educator
        url = reverse("appointments:conversation", args=[conversation.pk])
    else:
        other = conversation.resident
        url = reverse("rdv:write", args=[conversation.educator_id])
    author = message.author.first_name or message.author.get_username()
    push(
        other,
        title="Nouveau message",
        body=f"{author} vous a écrit.",
        url=url,
        tag=f"conversation-{conversation.pk}",
    )
