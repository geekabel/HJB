"""Messages of the staff (card T20): templates and composer.

Sending (now or later, reminders) comes with card T21; the composer saves
drafts and sends a test to its author.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.formats import date_format
from django.views.decorators.http import require_POST

from accounts.models import User
from housing.models import Room
from polls.forms import PollForm
from polls.models import Poll
from polls.services import MIN_VOTERS_FOR_RESULTS, poll_of, set_options
from polls.services import is_closed as poll_closed
from polls.services import results as poll_results
from sms.segments import analyze
from sms.service import MAX_SEGMENTS

from . import receipts, replies, sending
from .audience import audience, rendered
from .forms import CampaignForm, TemplateForm
from .models import Campaign, Delivery, MessageTemplate, MessageType, ReplyType
from .placeholders import FIELDS, fill, missing_values, uses_event_fields, values_for
from .services import find_target, sample_recipient, send_test
from .sms_text import GSM, REPLACEMENTS, words_with

PERMISSION = "accounts.send_messages"
TEST_DELAY = 60  # seconds between two tests of the same person


@login_required
@permission_required(PERMISSION, raise_exception=True)
def campaign_list(request):
    campaigns = Campaign.objects.select_related("author")
    status = Campaign.Status
    return render(
        request,
        "messaging/list.html",
        {
            "active_nav": "messages",
            "campaigns": campaigns.filter(status=status.DRAFT),
            "scheduled": campaigns.filter(status=status.SCHEDULED).order_by("send_at"),
            "sending": campaigns.filter(status=status.SENDING),
            "sent": campaigns.filter(status__in=[status.SENT, status.CANCELLED]).order_by(
                "-sent_at", "-updated_at"
            )[:30],
        },
    )


def _sms_report(campaign, audience_):
    """What the SMS will cost, for the longest one, and why."""
    source = campaign.sms_body or campaign.body
    sms_recipients = [r for r in audience_.recipients if r.channel == "sms"]
    texts = [rendered(campaign, r)[1] for r in sms_recipients]
    if not texts:
        sample = audience_.recipients[0] if audience_.recipients else _nobody()
        texts = [rendered(campaign, sample)[1]]
    sizes = {text: analyze(text) for text in texts}
    longest = max(texts, key=lambda t: (sizes[t].segments, sizes[t].units))
    info = analyze(longest)
    replaced = [c for c in dict.fromkeys(source) if c not in GSM and c in REPLACEMENTS]
    limit = 160 if info.encoding == "GSM-7" else 70
    if info.segments > 1:
        limit = (153 if info.encoding == "GSM-7" else 67) * info.segments
    return {
        "text": longest,  # the preview shows the longest: the counts below are for it
        "info": info,
        "varies": len({sizes[t].segments for t in texts}) > 1,
        "limit": limit,
        "replaced": [(c, REPLACEMENTS[c]) for c in replaced],
        "kept": [(c, words_with(longest, c)) for c in info.non_gsm],
        "too_long": info.segments > MAX_SEGMENTS,
        "from_full_text": not campaign.sms_body,
        "total_segments": info.segments * len(sms_recipients),
    }


def _nobody():
    from .audience import Recipient

    return Recipient(None, None, "none")


def _added(campaign):
    return list(campaign.rooms.all()), list(campaign.people.all()), list(campaign.excluded.all())


def _compose_page(request, form, campaign, poll_form=None):
    audience_ = audience(campaign) if campaign.pk else None
    sample = sample_recipient(campaign, request.user, audience_) if campaign.pk else None
    context = {
        "active_nav": "messages",
        "form": form,
        "campaign": campaign,
        "templates": MessageTemplate.objects.all(),
        "types": MessageType,
        "fields": FIELDS,
        "poll_form": poll_form or PollForm(poll=poll_of(campaign)),
        "error_count": len(form.errors) + (len(poll_form.errors) if poll_form else 0),
    }
    if campaign.pk:
        rooms, people, excluded = _added(campaign)
        values = values_for(campaign, sample.user, sample.room)
        context.update(
            {
                "audience": audience_,
                "sample": sample,
                "preview_title": fill(campaign.title, values),
                "preview_body": fill(campaign.body, values),
                "sms": _sms_report(campaign, audience_),
                "added_rooms": rooms,
                "added_people": people,
                "excluded": excluded,
                "missing": missing_values(campaign),
                "uses_event": uses_event_fields(campaign),
            }
        )
    return render(request, "messaging/compose.html", context)


def _from_template(template):
    return Campaign(
        type=template.type,
        template=template,
        title=template.title,
        body=template.body,
        sms_body=template.sms_body,
        reply_type=ReplyType.ATTENDANCE if template.reply_expected else ReplyType.NONE,
    )


@login_required
@permission_required(PERMISSION, raise_exception=True)
def compose(request, pk=None):
    if pk is None:
        campaign = Campaign(author=request.user)
        template_pk = request.GET.get("modele", "")
        if template_pk.isdigit():
            template = MessageTemplate.objects.filter(pk=template_pk).first()
            if template:
                campaign = _from_template(template)
                campaign.author = request.user
    else:
        campaign = get_object_or_404(Campaign, pk=pk)
        if campaign.status != Campaign.Status.DRAFT:
            return redirect("messaging:tracking", pk=campaign.pk)

    if request.method != "POST":
        return _compose_page(request, CampaignForm(instance=campaign), campaign)

    form = CampaignForm(request.POST, instance=campaign)
    poll_form = PollForm(request.POST, partial=True)
    is_vote = request.POST.get("type") == MessageType.VOTE
    if not form.is_valid() or (is_vote and not poll_form.is_valid()):
        if not is_vote:
            poll_form = None
        return _compose_page(request, form, campaign, poll_form)
    with transaction.atomic():
        # Confirmed in another tab meanwhile: a late save must not turn it back into a draft.
        if (
            campaign.pk
            and not Campaign.objects.select_for_update()
            .filter(pk=campaign.pk, status=Campaign.Status.DRAFT)
            .exists()
        ):
            messages.warning(
                request, "Ce message vient d'être confirmé : il n'est plus modifiable."
            )
            return redirect("messaging:tracking", pk=campaign.pk)
        campaign = form.save()
        _save_poll(campaign, poll_form if is_vote else None)
    action = request.POST.get("action", "save")
    done = _apply(request, campaign, action, form.cleaned_data.get("add", ""))
    if done is not None:
        return done
    return redirect("messaging:compose", pk=campaign.pk)


def _save_poll(campaign, poll_form):
    """The poll of a vote (card T25).

    Another type keeps the poll of the draft, in case of a wrong click:
    schedule() deletes it if the message is not a vote when it leaves.
    """
    if poll_form is None:
        return
    poll, _ = Poll.objects.get_or_create(campaign=campaign)
    poll.closes_at = poll_form.cleaned_data["closes_at"]
    poll.allow_comment = poll_form.cleaned_data["allow_comment"]
    poll.save()
    set_options(poll, poll_form.cleaned_data["options"])


def _apply(request, campaign, action, add):
    """Run the button that was pressed. Return a response, or None for the edit page."""
    kind, _, value = action.partition(":")
    if kind == "add" and not add.strip():
        kind = "save"  # Enter in a text field presses the first button: "Ajouter"
    if kind == "save":
        messages.success(request, f"Brouillon enregistré à {timezone.localtime():%H:%M}.")
    elif kind == "review":
        return redirect("messaging:review", pk=campaign.pk)
    elif kind == "add":
        room, person, error = find_target(add)
        if error:
            messages.warning(request, error)
        elif room:
            campaign.rooms.add(room)
            messages.success(request, f"Chambre {room.number} ajoutée.")
        else:
            campaign.people.add(person)
            campaign.excluded.remove(person)
            messages.success(request, f"{person.get_full_name() or person} ajouté(e).")
    elif kind in ("remove_room", "remove_person", "exclude", "restore") and value.isdigit():
        if kind == "remove_room":
            campaign.rooms.remove(*Room.objects.filter(pk=value))
        else:
            person = User.objects.filter(pk=value).first()
            if person and kind == "remove_person":
                campaign.people.remove(person)
            elif person and kind == "exclude":
                # Kept in the added people: "Remettre" brings the person back.
                campaign.excluded.add(person)
            elif person:
                campaign.excluded.remove(person)
    elif kind == "test":
        key = f"message-test:{request.user.pk}"
        if not cache.add(key, True, TEST_DELAY):
            messages.info(
                request, "Un essai vient de partir. Attendez une minute avant le suivant."
            )
        else:
            try:
                lines = send_test(
                    campaign, request.user, by_sms=request.POST.get("test_sms") == "yes"
                )
            except ImproperlyConfigured:
                lines = ["Les notifications ne sont pas configurées sur le serveur."]
            for line in lines:
                messages.info(request, line)
    return None


@login_required
@permission_required(PERMISSION, raise_exception=True)
def review(request, pk):
    """Last check before sending: what leaves, to whom, when, for how much."""
    campaign = get_object_or_404(Campaign, pk=pk, status=Campaign.Status.DRAFT)
    planned = campaign.send_at  # None: now
    send_at = planned or timezone.now()
    found = sending.problems(campaign, send_at)
    if request.method == "POST" and not found:
        try:
            sending.schedule(campaign, send_at=send_at, by=request.user, request=request)
        except ValidationError as error:
            found = error.messages
        else:
            if planned:
                when = date_format(timezone.localtime(send_at), "l j F à H:i")
                messages.success(request, f"Envoi programmé le {when}.")
            else:
                messages.success(request, "Envoi en cours.")
            return redirect("messaging:tracking", pk=campaign.pk)
    audience_ = audience(campaign)
    sms = _sms_report(campaign, audience_)
    return render(
        request,
        "messaging/review.html",
        {
            "active_nav": "messages",
            "campaign": campaign,
            "send_at": campaign.send_at,
            "remind_at": sending.reminder_time(campaign),
            "poll": poll_of(campaign),
            "audience": audience_,
            "sms": sms,
            # Until residents can answer (card T22), the reminder goes to everyone reached.
            "reminder_sms": sms["total_segments"] if sending.reminder_time(campaign) else 0,
            "problems": found,
        },
    )


@login_required
@permission_required(PERMISSION, raise_exception=True)
def tracking(request, pk):
    """A message after its confirmation: scheduled, being sent, or sent."""
    campaign = get_object_or_404(Campaign.objects.select_related("author"), pk=pk)
    if campaign.status == Campaign.Status.DRAFT:
        return redirect("messaging:compose", pk=campaign.pk)
    deliveries = campaign.deliveries.select_related("recipient").order_by(
        "kind", "room_number", "recipient__last_name"
    )
    poll = poll_of(campaign)
    vote = None
    if poll is not None:
        vote = {
            "poll": poll,
            "results": poll_results(poll),
            "closed": poll_closed(poll),
            "min_voters": MIN_VOTERS_FOR_RESULTS,
            # Every recipient: an SMS marked failed may have arrived (and voted).
            "reached": campaign.deliveries.filter(kind=Delivery.Kind.MESSAGE).count(),
            "voters": set(poll.participations.values_list("resident_id", flat=True)),
        }
    return render(
        request,
        "messaging/tracking.html",
        {
            "active_nav": "messages",
            "campaign": campaign,
            "display_title": fill(campaign.title, values_for(campaign)),
            "deliveries": deliveries,
            "stats": sending.summary(campaign),
            "reminder_stats": sending.summary(campaign, Delivery.Kind.REMINDER),
            "answers": replies.counts(campaign) if campaign.reply_type == "attendance" else None,
            "receipts": receipts.summary(campaign),
            "to_warn": receipts.to_warn(campaign),
            "vote": vote,
            "audience": audience(campaign)
            if campaign.status == Campaign.Status.SCHEDULED
            else None,
        },
    )


@require_POST
@login_required
@permission_required(PERMISSION, raise_exception=True)
def cancel_reminder(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    if sending.cancel_reminder(campaign, by=request.user, request=request):
        messages.success(request, "Relance annulée.")
    else:
        messages.warning(request, "Trop tard : la relance est déjà partie.")
    return redirect("messaging:tracking", pk=campaign.pk)


@require_POST
@login_required
@permission_required(PERMISSION, raise_exception=True)
def cancel(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    back_to_draft = request.POST.get("to") == "draft"
    if sending.cancel(campaign, by=request.user, back_to_draft=back_to_draft, request=request):
        if back_to_draft:
            messages.success(request, "Envoi annulé : le message est redevenu un brouillon.")
            return redirect("messaging:compose", pk=campaign.pk)
        messages.success(request, "Envoi annulé.")
    else:
        messages.warning(request, "Trop tard : l'envoi a déjà commencé.")
    return redirect("messaging:tracking", pk=campaign.pk)


@require_POST
@login_required
@permission_required(PERMISSION, raise_exception=True)
def campaign_delete(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk, status=Campaign.Status.DRAFT)
    campaign.delete()
    messages.success(request, "Brouillon supprimé.")
    return redirect("messaging:list")


@login_required
@permission_required(PERMISSION, raise_exception=True)
def template_list(request):
    return render(
        request,
        "messaging/templates.html",
        {"active_nav": "messages", "templates": MessageTemplate.objects.all()},
    )


@login_required
@permission_required(PERMISSION, raise_exception=True)
def template_edit(request, pk=None):
    template = get_object_or_404(MessageTemplate, pk=pk) if pk else MessageTemplate()
    form = TemplateForm(request.POST or None, instance=template)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Modèle « {template.name} » enregistré.")
        return redirect("messaging:templates")
    return render(
        request,
        "messaging/template_form.html",
        {"active_nav": "messages", "form": form, "template": template, "fields": FIELDS},
    )


@require_POST
@login_required
@permission_required(PERMISSION, raise_exception=True)
def template_delete(request, pk):
    template = get_object_or_404(MessageTemplate, pk=pk)
    template.delete()
    messages.success(request, f"Modèle « {template.name} » supprimé.")
    return redirect("messaging:templates")
