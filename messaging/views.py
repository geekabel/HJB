"""Messages of the staff (card T20): templates and composer.

Sending (now or later, reminders) comes with card T21; the composer saves
drafts and sends a test to its author.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import User
from housing.models import Room
from sms.segments import analyze
from sms.service import MAX_SEGMENTS

from .audience import audience, rendered
from .forms import CampaignForm, TemplateForm
from .models import Campaign, MessageTemplate, MessageType, ReplyType
from .placeholders import FIELDS, fill, missing_values, values_for
from .services import find_target, sample_recipient, send_test
from .sms_text import GSM, REPLACEMENTS, words_with

PERMISSION = "accounts.send_messages"
TEST_DELAY = 60  # seconds between two tests of the same person


@login_required
@permission_required(PERMISSION, raise_exception=True)
def campaign_list(request):
    campaigns = Campaign.objects.select_related("author").filter(status=Campaign.Status.DRAFT)
    return render(
        request,
        "messaging/list.html",
        {"active_nav": "messages", "campaigns": campaigns},
    )


def _sms_report(campaign, audience_):
    """What the SMS will cost, for the longest one, and why."""
    source = campaign.sms_body or campaign.body
    sms_recipients = [r for r in audience_.recipients if r.channel == "sms"]
    texts = [rendered(campaign, r)[1] for r in sms_recipients]
    if not texts:
        sample = audience_.recipients[0] if audience_.recipients else None
        texts = [rendered(campaign, sample)[1]] if sample else [rendered(campaign, _nobody())[1]]
    longest = max(texts, key=lambda t: analyze(t).segments * 1000 + analyze(t).units)
    info = analyze(longest)
    replaced = [c for c in dict.fromkeys(source) if c not in GSM and c in REPLACEMENTS]
    limit = 160 if info.encoding == "GSM-7" else 70
    if info.segments > 1:
        limit = (153 if info.encoding == "GSM-7" else 67) * info.segments
    return {
        "text": texts[0],
        "info": info,
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


def _compose_page(request, form, campaign):
    audience_ = audience(campaign) if campaign.pk else None
    sample = sample_recipient(campaign, request.user) if campaign.pk else None
    context = {
        "active_nav": "messages",
        "form": form,
        "campaign": campaign,
        "templates": MessageTemplate.objects.all(),
        "types": MessageType,
        "fields": FIELDS,
    }
    if campaign.pk:
        rooms, people, excluded = _added(campaign)
        values = values_for(campaign, sample.user, sample.room)
        context.update(
            {
                "audience": audience_,
                "sample": sample,
                "preview_title": campaign.title,
                "preview_body": fill(campaign.body, values),
                "sms": _sms_report(campaign, audience_),
                "added_rooms": rooms,
                "added_people": people,
                "excluded": excluded,
                "missing": missing_values(campaign),
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
        campaign = get_object_or_404(Campaign, pk=pk, status=Campaign.Status.DRAFT)

    if request.method != "POST":
        return _compose_page(request, CampaignForm(instance=campaign), campaign)

    form = CampaignForm(request.POST, instance=campaign)
    if not form.is_valid():
        return _compose_page(request, form, campaign)
    campaign = form.save()
    action = request.POST.get("action", "save")
    done = _apply(request, campaign, action, form.cleaned_data.get("add", ""))
    if done is not None:
        return done
    return redirect("messaging:compose", pk=campaign.pk)


def _apply(request, campaign, action, add):
    """Run the button that was pressed. Return a response, or None for the edit page."""
    kind, _, value = action.partition(":")
    if kind == "save":
        messages.success(request, f"Brouillon enregistré à {timezone.localtime():%H:%M}.")
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
                campaign.excluded.add(person)
                campaign.people.remove(person)
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
