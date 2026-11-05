"""Sending of the campaigns (card T21).

- schedule(): the staff confirm a message, now or for later. Checked first.
- run_due(): run every minute by "manage.py run_scheduled". Starts the
  campaigns and reminders whose time has come, resumes the interrupted ones,
  and records the planned departures.
- deliver(): the background task (messaging/tasks.py). One Delivery per
  person and kind; the unique constraint and the per-row claim mean that a
  person never gets the same message twice, even with two workers.

Channel: a notification first; an SMS only for a person without any device,
or whose devices could not be reached.
"""

import logging
from datetime import datetime, time, timedelta
from functools import partial

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import transaction
from django.utils import timezone

from audit.models import Action
from audit.service import log_action
from push.services import send_to_user
from push.vapid import vapid
from sms.providers.base import SmsError
from sms.segments import analyze
from sms.service import MAX_SEGMENTS, send_sms

from .audience import audience, rendered
from .models import AttendanceReply, Campaign, Delivery, ReplyType
from .placeholders import fill, missing_values, values_for

logger = logging.getLogger(__name__)

REMINDER_HOUR = time(8, 0)  # day of the event, at 8:00 (mockup P2)
REMINDER_PREFIX = "Rappel : "
MAX_SMS_ATTEMPTS = 3
RETRY_DELAY = timedelta(minutes=5)  # times the number of attempts
STALE_CLAIM = timedelta(minutes=10)  # a delivery "in progress" for longer: worker stopped
RESUME_AFTER = timedelta(minutes=5)  # a campaign still "sending" after this: resume it


# --- Checks and scheduling -------------------------------------------------


def reminder_time(campaign):
    if not (campaign.remind and campaign.event_date):
        return None
    return timezone.make_aware(datetime.combine(campaign.event_date, REMINDER_HOUR))


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
    if campaign.remind:
        if campaign.reply_type != ReplyType.ATTENDANCE:
            found.append("La relance demande une réponse « Présent » ou « Absent ».")
        elif not campaign.event_date:
            found.append("La relance a lieu le jour de la date du message : indiquez cette date.")
        elif reminder_time(campaign) <= send_at:
            found.append("La relance (le jour J à 8 h) tomberait avant l'envoi.")
    try:
        vapid()
    except ImproperlyConfigured:
        found.append("Les notifications ne sont pas configurées sur le serveur.")
    return found


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


def run_due(now=None):
    """Start what is due. Return a dict of counts (for the command output)."""
    now = now or timezone.now()
    counts = {"messages": 0, "reminders": 0, "resumed": 0, "departures": 0}
    for pk in Campaign.objects.filter(
        status=Campaign.Status.SCHEDULED, send_at__lte=now
    ).values_list("pk", flat=True):
        _enqueue(pk, Delivery.Kind.MESSAGE)
        counts["messages"] += 1
    for pk in Campaign.objects.filter(
        status=Campaign.Status.SENT, remind_at__lte=now, reminder_started_at__isnull=True
    ).values_list("pk", flat=True):
        _enqueue(pk, Delivery.Kind.REMINDER)
        counts["reminders"] += 1
    # Interrupted (worker stopped) or waiting for an SMS retry.
    stuck = Campaign.objects.filter(
        status=Campaign.Status.SENDING, started_at__lte=now - RESUME_AFTER
    )
    for pk in stuck.values_list("pk", flat=True):
        _enqueue(pk, Delivery.Kind.MESSAGE)
        counts["resumed"] += 1
    reminders = Campaign.objects.filter(
        reminder_started_at__lte=now - RESUME_AFTER,
        deliveries__kind=Delivery.Kind.REMINDER,
        deliveries__status__in=[Delivery.Status.PENDING, Delivery.Status.SENDING],
    ).distinct()
    for pk in reminders.values_list("pk", flat=True):
        _enqueue(pk, Delivery.Kind.REMINDER)
        counts["resumed"] += 1
    counts["departures"] = record_planned_departures(now)
    return counts


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
        except Exception:
            # One error must not stop the others; the next run tries again.
            logger.exception("Planned departure failed for stay %s", stay.pk)
    return done


# --- The task ---------------------------------------------------------------


def deliver(campaign_id, kind=Delivery.Kind.MESSAGE):
    """Send the message (or the reminder) of a campaign. Safe to run twice."""
    now = timezone.now()
    campaign = Campaign.objects.filter(pk=campaign_id).first()
    if campaign is None:
        return
    if kind == Delivery.Kind.MESSAGE:
        started = Campaign.objects.filter(
            pk=campaign.pk, status=Campaign.Status.SCHEDULED, send_at__lte=now
        ).update(status=Campaign.Status.SENDING, started_at=now)
        if started:
            _create_deliveries(campaign, kind)
        elif not Campaign.objects.filter(pk=campaign.pk, status=Campaign.Status.SENDING).exists():
            return  # cancelled, back to draft, or already sent
    else:
        started = Campaign.objects.filter(
            pk=campaign.pk, status=Campaign.Status.SENT, reminder_started_at__isnull=True
        ).update(reminder_started_at=now)
        if started:
            _create_reminders(campaign)
        elif not campaign.deliveries.filter(
            kind=kind, status__in=[Delivery.Status.PENDING, Delivery.Status.SENDING]
        ).exists():
            return
    campaign.refresh_from_db()
    _process(campaign, kind)
    if kind == Delivery.Kind.MESSAGE:
        _finish(campaign)


def _create_deliveries(campaign, kind):
    rows = []
    for recipient in audience(campaign).recipients:
        values = values_for(campaign, recipient.user, recipient.room)
        body, sms = rendered(campaign, recipient)
        rows.append(
            Delivery(
                campaign=campaign,
                recipient=recipient.user,
                kind=kind,
                channel=recipient.channel,
                room_number=recipient.room.number if recipient.room else "",
                title=fill(campaign.title, values)[:80],
                body=body,
                sms_text=sms,
            )
        )
    # A second run creates nothing: one delivery per person and kind.
    Delivery.objects.bulk_create(rows, ignore_conflicts=True)


def _create_reminders(campaign):
    answered = AttendanceReply.objects.filter(campaign=campaign).values_list(
        "resident_id", flat=True
    )
    first = campaign.deliveries.filter(
        kind=Delivery.Kind.MESSAGE, status=Delivery.Status.SENT, recipient__is_active=True
    ).exclude(recipient__in=answered)
    rows = [
        Delivery(
            campaign=campaign,
            recipient_id=d.recipient_id,
            kind=Delivery.Kind.REMINDER,
            channel=d.channel,
            room_number=d.room_number,
            title=(REMINDER_PREFIX + d.title)[:80],
            body=d.body,
            sms_text=REMINDER_PREFIX + d.sms_text if d.sms_text else "",
        )
        for d in first
    ]
    Delivery.objects.bulk_create(rows, ignore_conflicts=True)


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


def _send_one(campaign, delivery):
    user = delivery.recipient
    if delivery.channel == Delivery.Channel.PUSH:
        result = send_to_user(
            user,
            title=delivery.title,
            body=delivery.body,
            url="/",
            tag=f"message-{campaign.pk}",
            urgency="high" if delivery.kind == Delivery.Kind.REMINDER else "normal",
        )
        if result.sent:
            delivery.status = Delivery.Status.SENT
            delivery.sent_at = timezone.now()
            return
        if not user.phone:
            delivery.status = Delivery.Status.FAILED
            delivery.error = "Aucun appareil n'a pu être atteint, et pas de numéro."
            return
        # No device reached: the SMS takes over.
        delivery.channel = Delivery.Channel.SMS
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
    delivery.segments = analyze(delivery.sms_text).segments


def _finish(campaign):
    open_ = campaign.deliveries.filter(
        kind=Delivery.Kind.MESSAGE, status__in=[Delivery.Status.PENDING, Delivery.Status.SENDING]
    )
    if open_.exists():
        return  # SMS to retry later: run_due() resumes the campaign
    finished = Campaign.objects.filter(pk=campaign.pk, status=Campaign.Status.SENDING).update(
        status=Campaign.Status.SENT, sent_at=timezone.now()
    )
    if finished:
        stats = summary(campaign)
        log_action(Action.MESSAGE_SENT, target=campaign, details=stats)


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
