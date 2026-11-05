"""Background tasks of the appointments (cards T28, T29).

Docs: https://docs.djangoproject.com/en/6.1/topics/tasks/
Arguments are ids only: the task rows show in the admin site, and must not
tell who writes to or meets whom.
"""

import logging

from django.core.exceptions import ImproperlyConfigured
from django.tasks import task
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format

from push.services import send_to_user
from sms.providers.base import SmsError
from sms.segments import analyze
from sms.service import send_sms

from . import reminders
from .models import Appointment, DirectMessage

logger = logging.getLogger(__name__)


def push(user, *, title, body, url, tag, **options):
    """A notification on the devices of the person (best effort). Return the SendResult."""
    if user is None or not user.is_active:
        return None
    try:
        return send_to_user(user, title=title, body=body, url=url, tag=tag, **options)
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


def _when(meeting):
    start = timezone.localtime(meeting.start)
    return start, f"{date_format(start, 'l j F')} à {start:%H:%M}"


def _sms(user, text):
    """The SMS fallback, for a resident without the application (best effort)."""
    from messaging.sending import sms_ready

    if not (user.is_active and user.phone and sms_ready()):
        return False
    try:
        send_sms(user.phone, text)
    except SmsError as error:
        logger.warning("Appointment SMS not sent: %s", type(error).__name__)
        return False
    logger.info("Appointment SMS sent: %s segment(s)", analyze(text).segments)
    return True


def _reach(user, *, title, body, url, tag, sms="", **options):
    """A notification; an SMS (``sms``) only for a person without any device.

    A device that did not answer (push service down) gets no paid SMS: the
    same rule as the messages (messaging.sending).
    """
    result = push(user, title=title, body=body, url=url, tag=tag, **options)
    if sms and result is not None and not result.sent and not result.failed:
        _sms(user, sms)


def _until(start, now):
    """Seconds the push service keeps the reminder: never shown after the start."""
    return max(60, int((start - now).total_seconds()))


@task
def remind_task(meeting_id, kind):
    """Reminder of a meeting: "day_before" (SMS fallback) or "hour_before"."""
    meeting = (
        Appointment.objects.filter(pk=meeting_id, status=Appointment.Status.CONFIRMED)
        .select_related("educator", "resident")
        .first()
    )
    if meeting is None:
        return  # cancelled meanwhile
    # The queue may run late (worker stopped, long campaign): check again.
    now = timezone.now()
    if kind == "day_before":
        if not reminders.day_before_due(meeting, now):
            return
    elif meeting.start <= now + reminders.HOUR_BEFORE_LATEST:
        return
    start, when = _when(meeting)
    who = meeting.educator.first_name or meeting.educator.get_username()
    options = {
        "url": reverse("rdv:detail", args=[meeting.pk]),
        "tag": f"rendez-vous-{meeting.pk}",
        "ttl": _until(meeting.start, now),
    }
    if kind == "day_before":
        _reach(
            meeting.resident,
            title="Rappel de rendez-vous",
            body=f"Rendez-vous demain, {when}, avec {who}.",
            sms=f"HJB : rappel, rendez-vous demain {when} avec {who}.",
            **options,
        )
    else:
        _reach(
            meeting.resident,
            title="Rendez-vous bientôt",
            body=f"Rendez-vous aujourd'hui à {start:%H:%M} avec {who}.",
            **options,
        )


@task
def cancel_notice_task(meeting_id):
    """Tell the other person that a meeting is cancelled."""
    meeting = (
        Appointment.objects.filter(pk=meeting_id, status=Appointment.Status.CANCELLED)
        .select_related("educator", "resident")
        .first()
    )
    if meeting is None:
        return
    _start, when = _when(meeting)
    if meeting.cancelled_by_id == meeting.resident_id:
        name = meeting.resident.first_name or meeting.resident.get_username()
        push(
            meeting.educator,
            title="Rendez-vous annulé",
            body=f"{name} a annulé le rendez-vous du {when}.",
            url=reverse("appointments:availability"),
            tag=f"rendez-vous-{meeting.pk}",
        )
    elif meeting.cancelled_by_id == meeting.educator_id:
        who = meeting.educator.first_name or meeting.educator.get_username()
        body = f"{who} a annulé votre rendez-vous du {when}. Vous pouvez en reprendre un."
        _reach(
            meeting.resident,
            title="Rendez-vous annulé",
            body=body,
            url=reverse("rdv:book"),
            tag=f"rendez-vous-{meeting.pk}",
            sms=f"HJB : {body}",
            ttl=_until(meeting.start, timezone.now()),
        )
