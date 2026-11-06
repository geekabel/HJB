"""Sending of the campaigns (card T21).

- schedule(): the staff confirm a message, now or for later. Checked first.
- run_due(): run every minute by "manage.py run_scheduled". Starts the
  campaigns and reminders whose time has come, resumes the interrupted ones,
  and records the planned departures.
- deliver(): the background task (messaging/tasks.py). One Delivery per
  person and kind; the unique constraint and the per-row claim mean that a
  person never gets the same message twice, even with two workers.

Channel: a notification for a person with at least one device; an SMS for a
person without any device (none subscribed, or all of them gone for good). A
notification that fails for a while (push service down) is tried again, never
replaced by a paid SMS.
"""

import logging
from datetime import datetime, time, timedelta
from functools import partial

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone

from audit.models import Action
from audit.service import log_action
from polls.models import Participation, Poll
from polls.services import MIN_OPTIONS, REMINDER_BEFORE_CLOSING, poll_of
from push.models import PushSubscription
from push.services import send_to_user
from push.vapid import vapid
from sms.providers.base import SmsError
from sms.segments import analyze
from sms.service import MAX_SEGMENTS, send_sms

from .audience import audience, rendered
from .models import AttendanceReply, Campaign, Delivery, MessageType, Receipt, ReplyType
from .placeholders import fill, missing_values, values_for
from .receipts import apply_early
from .replies import closes_at, reply_path
from .replies import is_open as replies_open

logger = logging.getLogger(__name__)

REMINDER_HOUR = time(8, 0)  # day of the event, at 8:00 (mockup P2)
REMINDER_PREFIX = "Rappel : "
MAX_SMS_ATTEMPTS = 3
RETRY_DELAY = timedelta(minutes=5)  # times the number of attempts
STALE_CLAIM = timedelta(minutes=10)  # a delivery "in progress" for longer: worker stopped
RESUME_AFTER = timedelta(minutes=5)  # a campaign still "sending" after this: resume it
ENQUEUE_AGAIN_AFTER = timedelta(minutes=10)  # no new task while the last one may still wait
MAX_PUSH_ATTEMPTS = 3
TOO_LATE = timedelta(hours=12)  # a message this late is not sent any more
REMINDER_TOO_LATE = timedelta(hours=4)  # the reminder of 8:00, not after noon
MIN_REMINDER_GAP = timedelta(hours=1)
# A vote reminder goes between these hours, never at night (card T25).
VOTE_REMINDER_EARLIEST = time(9, 0)
VOTE_REMINDER_LATEST = time(20, 0)


# --- Checks and scheduling -------------------------------------------------


def reminder_time(campaign):
    """The day of the event at 8:00; for a vote, 24 h before its closing (T25)."""
    if not campaign.remind:
        return None
    if campaign.type == MessageType.VOTE:
        poll = poll_of(campaign)
        if poll is None or poll.closes_at is None:
            return None
        return _daytime(poll.closes_at - REMINDER_BEFORE_CLOSING)
    if not campaign.event_date:
        return None
    return timezone.make_aware(datetime.combine(campaign.event_date, REMINDER_HOUR))


def _daytime(moment):
    """The same moment, or earlier, between 9:00 and 20:00: never at night."""
    local = timezone.localtime(moment)
    if local.time() > VOTE_REMINDER_LATEST:
        return timezone.make_aware(datetime.combine(local.date(), VOTE_REMINDER_LATEST))
    if local.time() < VOTE_REMINDER_EARLIEST:
        day = local.date() - timedelta(days=1)
        return timezone.make_aware(datetime.combine(day, VOTE_REMINDER_LATEST))
    return moment


def _vote_problems(campaign, send_at):
    poll = poll_of(campaign)
    found = []
    if poll is None or poll.options.count() < MIN_OPTIONS:
        found.append(f"Proposez au moins {MIN_OPTIONS} choix pour le vote.")
    if poll is None or poll.closes_at is None:
        found.append("Indiquez la date et l'heure de clôture du vote.")
    elif poll.closes_at <= send_at + MIN_REMINDER_GAP:
        found.append("La clôture du vote doit venir au moins une heure après l'envoi.")
    if campaign.reply_type == ReplyType.ATTENDANCE:
        found.append(
            "Un vote ne demande pas «\u00a0Présent\u00a0» ou «\u00a0Absent\u00a0» : "
            "retirez cette réponse."
        )
    if campaign.remind and reminder_time(campaign) is not None:
        if reminder_time(campaign) < send_at + MIN_REMINDER_GAP:
            found.append(
                "La relance (24 h avant la clôture) doit venir au moins une heure après "
                "l'envoi : avancez l'envoi ou repoussez la clôture."
            )
    if not settings.SITE_URL:
        found.append("L'adresse du site n'est pas réglée (DJANGO_SITE_URL) : pas de lien de vote.")
    return found


def problems(campaign, send_at):
    """French reasons why the campaign cannot be scheduled (empty list: fine)."""
    found = []
    targets = audience(campaign)
    if not targets.total:
        found.append("Aucun destinataire : choisissez un étage, une chambre ou une personne.")
    missing = missing_values(campaign)
    if missing:
        names = ", ".join(f"{{{name}}}" for name in missing)
        found.append(f"Indiquez la valeur de {names}.")
    if targets.sms:
        longest = max(
            (analyze(rendered(campaign, r)[1]) for r in targets.recipients if r.channel == "sms"),
            key=lambda info: info.segments,
        )
        if longest.segments > MAX_SEGMENTS:
            found.append(f"La version SMS est trop longue ({longest.segments} SMS).")
    if send_at < timezone.now() - timedelta(minutes=1):
        found.append("L'heure d'envoi est passée.")
    if campaign.type == MessageType.VOTE:
        found.extend(_vote_problems(campaign, send_at))
    elif campaign.remind:
        if campaign.reply_type != ReplyType.ATTENDANCE:
            found.append(
                "La relance demande une réponse «\u00a0Présent\u00a0» ou «\u00a0Absent\u00a0»."
            )
        elif not campaign.event_date:
            found.append("La relance a lieu le jour de la date du message : indiquez cette date.")
        elif reminder_time(campaign) < send_at + MIN_REMINDER_GAP:
            found.append(
                "La relance (le jour J à 8 h) doit venir au moins une heure après l'envoi."
            )
    if (
        campaign.reply_type == ReplyType.ATTENDANCE
        and campaign.event_date
        and closes_at(campaign) <= send_at + MIN_REMINDER_GAP
    ):
        # The answers close at the end of the event day: the link would be useless.
        found.append("La date du message est passée ou trop proche : plus de réponse possible.")
    if campaign.reply_type == ReplyType.ATTENDANCE and not settings.SITE_URL:
        found.append(
            "L'adresse du site n'est pas réglée (DJANGO_SITE_URL) : pas de lien de réponse."
        )
    try:
        vapid()
    except ImproperlyConfigured:
        found.append("Les notifications ne sont pas configurées sur le serveur.")
    if targets.sms and not sms_ready():
        found.append(
            "L'envoi de SMS n'est pas configuré sur le serveur : "
            "les résidents sans l'application ne recevraient rien."
        )
    return found


def sms_ready():
    from sms.service import active_provider

    try:
        provider = active_provider()
    except SmsError:
        return False
    return provider.name != "disabled" and not provider.missing_options()


def schedule(campaign, *, send_at, by, request=None):
    """Confirm the sending of a draft. Raise ValidationError with the problems."""
    found = problems(campaign, send_at)
    if found:
        raise ValidationError(found)
    with transaction.atomic():
        updated = Campaign.objects.filter(pk=campaign.pk, status=Campaign.Status.DRAFT).update(
            status=Campaign.Status.SCHEDULED,
            send_at=send_at,
            remind_at=reminder_time(campaign),
        )
        if not updated:
            raise ValidationError("Ce message n'est plus un brouillon.")
        if campaign.type != MessageType.VOTE:
            # Kept in the draft after a change of type (card T25): not sent.
            Poll.objects.filter(campaign=campaign).delete()
        campaign.refresh_from_db()
        targets = audience(campaign)
        log_action(
            Action.MESSAGE_SCHEDULED,
            actor=by,
            target=campaign,
            details={
                "send_at": timezone.localtime(send_at).isoformat(timespec="minutes"),
                "recipients": targets.total,
                "push": targets.push,
                "sms": targets.sms,
            },
            request=request,
        )
        if send_at <= timezone.now():
            Campaign.objects.filter(pk=campaign.pk).update(enqueued_at=timezone.now())
            transaction.on_commit(partial(_enqueue, campaign.pk, Delivery.Kind.MESSAGE))
    return campaign


def cancel(campaign, *, by, back_to_draft=False, request=None):
    """Stop a scheduled message before it starts. Return False if it already started."""
    status = Campaign.Status.DRAFT if back_to_draft else Campaign.Status.CANCELLED
    with transaction.atomic():
        updated = Campaign.objects.filter(pk=campaign.pk, status=Campaign.Status.SCHEDULED).update(
            status=status, send_at=None, remind_at=None
        )
        if updated:
            log_action(
                Action.MESSAGE_CANCELLED,
                actor=by,
                target=campaign,
                details={"back_to_draft": back_to_draft},
                request=request,
            )
    return bool(updated)


def _enqueue(campaign_id, kind):
    from .tasks import deliver_task

    deliver_task.enqueue(campaign_id, kind)


# --- The periodic command ---------------------------------------------------


def _claim_enqueue(queryset, field, now):
    """Enqueue a task only if none was enqueued recently for this campaign and kind.

    The worker may be down: without this, the command run every minute would
    pile up one task per minute (they would do nothing, but fill the queue).
    """
    stale = now - ENQUEUE_AGAIN_AFTER
    ids = []
    for pk in queryset.values_list("pk", flat=True):
        claimed = (
            Campaign.objects.filter(pk=pk)
            .filter(models.Q(**{f"{field}__isnull": True}) | models.Q(**{f"{field}__lte": stale}))
            .update(**{field: now})
        )
        if claimed:
            ids.append(pk)
    return ids


def run_due(now=None):
    """Start what is due. Return a dict of counts (for the command output)."""
    now = now or timezone.now()
    counts = {"messages": 0, "reminders": 0, "resumed": 0, "late": 0, "departures": 0}
    status = Campaign.Status

    # Far too late (worker down for hours): not sent any more, and said so.
    for campaign in Campaign.objects.filter(status=status.SCHEDULED, send_at__lte=now - TOO_LATE):
        if Campaign.objects.filter(pk=campaign.pk, status=status.SCHEDULED).update(
            status=status.CANCELLED
        ):
            log_action(Action.MESSAGE_CANCELLED, target=campaign, details={"too_late": True})
            counts["late"] += 1
    for campaign in Campaign.objects.filter(
        status=status.SENT,
        remind_at__lte=now - REMINDER_TOO_LATE,
        reminder_started_at__isnull=True,
    ):
        if Campaign.objects.filter(pk=campaign.pk, reminder_started_at__isnull=True).update(
            reminder_started_at=now
        ):
            log_action(
                Action.MESSAGE_CANCELLED, target=campaign, details={"reminder_too_late": True}
            )
            counts["late"] += 1

    due = Campaign.objects.filter(status=status.SCHEDULED, send_at__lte=now)
    for pk in _claim_enqueue(due, "enqueued_at", now):
        _enqueue(pk, Delivery.Kind.MESSAGE)
        counts["messages"] += 1
    reminders = Campaign.objects.filter(
        status=status.SENT, remind_at__lte=now, reminder_started_at__isnull=True
    )
    for pk in _claim_enqueue(reminders, "reminder_enqueued_at", now):
        _enqueue(pk, Delivery.Kind.REMINDER)
        counts["reminders"] += 1
    # Interrupted (worker stopped) or waiting for a new attempt.
    stuck = Campaign.objects.filter(status=status.SENDING, started_at__lte=now - RESUME_AFTER)
    for pk in _claim_enqueue(stuck, "enqueued_at", now):
        _enqueue(pk, Delivery.Kind.MESSAGE)
        counts["resumed"] += 1
    open_reminders = Campaign.objects.filter(
        reminder_started_at__lte=now - RESUME_AFTER,
        deliveries__kind=Delivery.Kind.REMINDER,
        deliveries__status__in=[Delivery.Status.PENDING, Delivery.Status.SENDING],
    ).distinct()
    for pk in _claim_enqueue(open_reminders, "reminder_enqueued_at", now):
        _enqueue(pk, Delivery.Kind.REMINDER)
        counts["resumed"] += 1
    counts["departures"] = record_planned_departures(now)
    return counts


def cancel_reminder(campaign, *, by, request=None):
    """Do not send the reminder of a sent message (the event was cancelled, for example)."""
    updated = Campaign.objects.filter(
        pk=campaign.pk, remind_at__isnull=False, reminder_started_at__isnull=True
    ).update(remind_at=None, remind=False)
    if updated:
        log_action(
            Action.MESSAGE_CANCELLED,
            actor=by,
            target=campaign,
            details={"reminder": True},
            request=request,
        )
    return bool(updated)


PLANNED_DEPARTURE_HOUR = time(12, 0)  # the day of the departure, after the usual check-out


def record_planned_departures(now=None):
    from housing.models import Stay
    from residents.departure import record_departure

    now = timezone.localtime(now or timezone.now())
    last_day = now.date() if now.time() >= PLANNED_DEPARTURE_HOUR else now.date() - timedelta(1)
    done = 0
    for stay in (
        Stay.objects.current().filter(planned_departure__lte=last_day).select_related("resident")
    ):
        try:
            record_departure(stay.resident, stay.planned_departure)
            done += 1
        except ValidationError as error:
            # A date that can no longer be recorded (before the arrival, for example):
            # the plan is dropped and noted in the audit log, instead of failing every minute.
            Stay.objects.filter(pk=stay.pk).update(planned_departure=None)
            log_action(
                Action.DEPARTURE_PLAN_CANCELLED,
                target=stay.resident,
                details={
                    "planned_departure": stay.planned_departure.isoformat(),
                    "reason": " ".join(error.messages),
                },
            )
            logger.warning("Planned departure of stay %s dropped: %s", stay.pk, error.messages)
        except Exception:
            # One error must not stop the others; the next run tries again.
            logger.exception("Planned departure failed for stay %s", stay.pk)
    return done


# --- The task ---------------------------------------------------------------


def _vote_already_closed(campaign, now):
    """A vote whose sending comes too late (worker stopped for hours): cancelled."""
    poll = poll_of(campaign) if campaign.type == MessageType.VOTE else None
    if poll is None or poll.closes_at is None or poll.closes_at > now + MIN_REMINDER_GAP:
        return False
    # Only a sending that has not started: one under way goes on.
    if not Campaign.objects.filter(pk=campaign.pk, status=Campaign.Status.SCHEDULED).update(
        status=Campaign.Status.CANCELLED, send_at=None, remind_at=None
    ):
        return False
    log_action(
        Action.MESSAGE_CANCELLED,
        target=campaign,
        details={"reason": "Vote clos ou presque à l'heure de l'envoi : rien n'est parti."},
    )
    logger.warning("Vote %s cancelled: closed before its sending", campaign.pk)
    return True


def deliver(campaign_id, kind=Delivery.Kind.MESSAGE):
    """Send the message (or the reminder) of a campaign. Safe to run twice."""
    now = timezone.now()
    campaign = Campaign.objects.filter(pk=campaign_id).first()
    if campaign is None:
        return
    if kind == Delivery.Kind.MESSAGE and _vote_already_closed(campaign, now):
        return
    if kind == Delivery.Kind.MESSAGE:
        # The start and the list of deliveries go together: a campaign is never
        # "sending" (then "sent") without its deliveries.
        with transaction.atomic():
            started = Campaign.objects.filter(
                pk=campaign.pk, status=Campaign.Status.SCHEDULED, send_at__lte=now
            ).update(status=Campaign.Status.SENDING, started_at=now)
            if started:
                _create_deliveries(campaign, kind)
        if not started and not (
            Campaign.objects.filter(pk=campaign.pk, status=Campaign.Status.SENDING).exists()
        ):
            return  # cancelled, back to draft, or already sent
    else:
        with transaction.atomic():
            started = Campaign.objects.filter(
                pk=campaign.pk,
                status=Campaign.Status.SENT,
                remind_at__isnull=False,
                reminder_started_at__isnull=True,
            ).update(reminder_started_at=now)
            if started:
                _create_reminders(campaign)
        if (
            not started
            and not campaign.deliveries.filter(
                kind=kind, status__in=[Delivery.Status.PENDING, Delivery.Status.SENDING]
            ).exists()
        ):
            return
    campaign.refresh_from_db()
    _process(campaign, kind)
    _finish(campaign, kind)


def _create_deliveries(campaign, kind):
    rows = []
    for recipient in audience(campaign).recipients:
        values = values_for(campaign, recipient.user, recipient.room)
        body, sms = rendered(campaign, recipient, live=True)
        rows.append(
            Delivery(
                campaign=campaign,
                recipient=recipient.user,
                kind=kind,
                channel=recipient.channel,
                room_number=recipient.room.number if recipient.room else "",
                personal=recipient.personal,
                title=fill(campaign.title, values)[:80],
                body=body,
                sms_text=sms,
            )
        )
    # A second run creates nothing: one delivery per person and kind.
    Delivery.objects.bulk_create(rows, ignore_conflicts=True)


def _answered(campaign):
    """People who answered: they get no reminder."""
    if campaign.type == MessageType.VOTE:
        return Participation.objects.filter(poll__campaign=campaign).values_list(
            "resident_id", flat=True
        )
    return AttendanceReply.objects.filter(campaign=campaign).values_list("resident_id", flat=True)


def _create_reminders(campaign):
    answered = _answered(campaign)
    first = list(
        campaign.deliveries.filter(
            kind=Delivery.Kind.MESSAGE, status=Delivery.Status.SENT, recipient__is_active=True
        )
        .exclude(recipient__in=answered)
        .select_related("recipient")
    )
    # The channel of today: someone who subscribed since gets a notification.
    with_device = set(
        PushSubscription.objects.filter(recipient_filter(first)).values_list("user_id", flat=True)
    )
    rows = []
    for d in first:
        channel = (
            Delivery.Channel.PUSH
            if d.recipient_id in with_device
            else (Delivery.Channel.SMS if d.recipient.phone else Delivery.Channel.NONE)
        )
        rows.append(
            Delivery(
                campaign=campaign,
                recipient_id=d.recipient_id,
                kind=Delivery.Kind.REMINDER,
                channel=channel,
                room_number=d.room_number,
                personal=d.personal,
                title=(REMINDER_PREFIX + d.title)[:80],
                body=d.body,
                sms_text=reminder_sms(d.sms_text),
            )
        )
    Delivery.objects.bulk_create(rows, ignore_conflicts=True)


def recipient_filter(deliveries):
    return models.Q(user_id__in=[d.recipient_id for d in deliveries])


def reminder_sms(text):
    """ "Rappel : " in front, unless it costs one more SMS."""
    if not text:
        return ""
    with_prefix = REMINDER_PREFIX + text
    return with_prefix if analyze(with_prefix).segments <= analyze(text).segments else text


def _process(campaign, kind):
    now = timezone.now()
    deliveries = campaign.deliveries.filter(kind=kind)
    # A worker stopped while sending: the message may have left. Never send it again.
    deliveries.filter(status=Delivery.Status.SENDING, claimed_at__lte=now - STALE_CLAIM).update(
        status=Delivery.Status.FAILED,
        error="Envoi interrompu : état inconnu, à vérifier avec la personne.",
    )
    pending = deliveries.filter(status=Delivery.Status.PENDING).exclude(next_attempt_at__gt=now)
    for delivery in pending.select_related("recipient"):
        # Claim the row: a second worker on the same campaign skips it.
        claimed = Delivery.objects.filter(pk=delivery.pk, status=Delivery.Status.PENDING).update(
            status=Delivery.Status.SENDING, claimed_at=timezone.now()
        )
        if not claimed:
            continue
        try:
            _send_one(campaign, delivery)
        except Exception:
            logger.exception("Delivery %s failed", delivery.pk)
            delivery.status = Delivery.Status.FAILED
            delivery.error = "Erreur inattendue."
        delivery.save()
        apply_early(delivery)  # a receipt may have come before this save


def _send_one(campaign, delivery):
    user = delivery.recipient
    if delivery.channel == Delivery.Channel.PUSH:
        delivery.attempts += 1
        result = send_to_user(
            user,
            title=delivery.title,
            body=delivery.body,
            url=reverse("inbox:message", args=[campaign.pk]),
            reply=reply_path(campaign.pk, user.pk) if replies_open(campaign) else "",
            tag=f"message-{campaign.pk}",
            urgency="high" if delivery.kind == Delivery.Kind.REMINDER else "normal",
        )
        if result.sent:
            delivery.status = Delivery.Status.SENT
            delivery.sent_at = timezone.now()
            delivery.error = ""
            return
        if result.failed:
            # A device is still there but did not answer (push service down,
            # timeout): try the notification again later, never a paid SMS.
            if delivery.attempts < MAX_PUSH_ATTEMPTS:
                delivery.status = Delivery.Status.PENDING
                delivery.next_attempt_at = timezone.now() + RETRY_DELAY * delivery.attempts
                delivery.error = "Notification pas encore remise : nouvel essai."
            else:
                delivery.status = Delivery.Status.FAILED
                delivery.error = "Notification non remise après plusieurs essais."
            return
        # No device left at all (they all answered "gone"): the SMS takes over.
        if not user.phone:
            delivery.status = Delivery.Status.FAILED
            delivery.error = "Plus aucun appareil, et pas de numéro."
            return
        delivery.channel = Delivery.Channel.SMS
        delivery.attempts = 0
    if delivery.channel == Delivery.Channel.SMS:
        _send_sms(delivery, user)
        return
    delivery.status = Delivery.Status.FAILED
    delivery.error = "Ni appareil ni numéro de téléphone."


def _send_sms(delivery, user):
    if not user.phone:
        delivery.status = Delivery.Status.FAILED
        delivery.error = "Pas de numéro de téléphone."
        return
    delivery.attempts += 1
    try:
        result = send_sms(user.phone, delivery.sms_text)
    except SmsError as error:
        if getattr(error, "uncertain", False):
            delivery.status = Delivery.Status.FAILED
            delivery.error = "Envoi incertain : le SMS est peut-être parti."
        elif error.temporary and delivery.attempts < MAX_SMS_ATTEMPTS:
            delivery.status = Delivery.Status.PENDING
            delivery.next_attempt_at = timezone.now() + RETRY_DELAY * delivery.attempts
            delivery.error = str(error)[:200]
        else:
            delivery.status = Delivery.Status.FAILED
            delivery.error = str(error)[:200]
        return
    delivery.status = Delivery.Status.SENT
    delivery.sent_at = timezone.now()
    delivery.provider_message_id = result.message_id[:64]
    delivery.sms_provider = result.provider[:20]
    if result.tracked:
        delivery.receipt = Receipt.PENDING
    delivery.segments = analyze(delivery.sms_text).segments


def _finish(campaign, kind):
    open_ = campaign.deliveries.filter(
        kind=kind, status__in=[Delivery.Status.PENDING, Delivery.Status.SENDING]
    )
    if open_.exists():
        return  # new attempts later: run_due() resumes the campaign
    if kind == Delivery.Kind.REMINDER:
        if not Campaign.objects.filter(pk=campaign.pk, reminder_sent_at__isnull=True).update(
            reminder_sent_at=timezone.now()
        ):
            return
        log_action(
            Action.MESSAGE_SENT,
            target=campaign,
            details={"reminder": True, **summary(campaign, kind)},
        )
        return
    finished = Campaign.objects.filter(pk=campaign.pk, status=Campaign.Status.SENDING).update(
        status=Campaign.Status.SENT, sent_at=timezone.now()
    )
    if finished:
        log_action(Action.MESSAGE_SENT, target=campaign, details=summary(campaign))


def summary(campaign, kind=Delivery.Kind.MESSAGE):
    deliveries = campaign.deliveries.filter(kind=kind)
    sent = deliveries.filter(status=Delivery.Status.SENT)
    return {
        "recipients": deliveries.count(),
        "push": sent.filter(channel=Delivery.Channel.PUSH).count(),
        "sms": sent.filter(channel=Delivery.Channel.SMS).count(),
        "segments": sum(sent.values_list("segments", flat=True)),
        "failed": deliveries.filter(status=Delivery.Status.FAILED).count(),
    }
