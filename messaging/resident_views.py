"""Pages of the residents for the messages (cards T22, T23).

- reply(): the personal link of the SMS and of the notification buttons. No
  session: the signed link is the proof. A GET only shows the page (SMS apps
  open links to make a preview); only the buttons (POST) record an answer.
- message(): one message in the application, with the same buttons.
- For a vote (card T25), both pages show the choices instead of the buttons.
- inbox_list(): the inbox, by kind; read_all() marks every message as read.
"""

from datetime import datetime, time

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.cache import add_never_cache_headers
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from access.session_policy import is_resident
from accounts.models import User
from appointments import direct
from polls import services as polls
from polls.services import VoteRefused, poll_of

from . import inbox, replies
from .models import AttendanceReply, Campaign, Delivery

THANKS = {
    "present": "C'est noté : vous serez présent. Merci !",
    "absent": "C'est noté : vous serez absent. Merci de l'avoir dit.",
}


INVALID = "Choisissez « Présent » ou « Absent »."
VOTE_THANKS = "Merci, votre vote est enregistré. Il reste anonyme."
PER_PAGE = 20


def _delivery(campaign, user):
    # A failed delivery too: an SMS marked uncertain may have arrived, and the
    # application shows every message received (card T23).
    return Delivery.objects.filter(
        campaign=campaign, recipient=user, kind=Delivery.Kind.MESSAGE
    ).first()


def _private(response):
    add_never_cache_headers(response)
    # The address holds the personal link: never sent to another site.
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex"
    return response


# The link is the proof, not a session cookie: no CSRF token is needed, and the
# buttons of a notification can answer without opening the application.
@csrf_exempt
@sensitive_post_parameters("option", "comment")  # never in an error report
@require_http_methods(["GET", "POST"])
def reply(request, token):
    found = replies.read_token(token)
    if found is None:
        raise Http404
    campaign = Campaign.objects.filter(pk=found[0]).first()
    resident = User.objects.filter(pk=found[1], is_active=True).first()
    delivery = _delivery(campaign, resident) if campaign and resident else None
    if delivery is None:
        raise Http404
    poll = poll_of(campaign)
    if poll is not None:
        return _vote_by_link(request, campaign, delivery, poll, resident)
    is_open = replies.is_open(campaign)
    thanks = error = ""
    status = 200
    if request.method == "POST":
        answer = request.POST.get("answer", "")
        if not is_open:
            status = 409
        elif answer not in THANKS:
            status, error = 400, INVALID
        else:
            replies.record(campaign, resident, answer)
            thanks = THANKS[answer]
        # Only a tap counts as read: an SMS app opens the link (GET) for a preview.
        if delivery.read_at is None:
            Delivery.objects.filter(pk=delivery.pk).update(read_at=timezone.now())
    current = AttendanceReply.objects.filter(campaign=campaign, resident=resident).first()
    return _private(
        render(
            request,
            "messaging/reply.html",
            {
                "campaign": campaign,
                "delivery": delivery,
                "current": current,
                "closed": not is_open,
                "closes_at": replies.closes_at(campaign),
                "thanks": thanks,
                "error": error,
            },
            status=status,
        )
    )


def _start_of_today():
    """For a vote, "read" keeps the day only: not the time of the vote."""
    return timezone.make_aware(datetime.combine(timezone.localdate(), time(0, 0)))


def _vote_by_link(request, campaign, delivery, poll, resident):
    thanks = error = comment = ""
    status = 200
    if request.method == "POST":
        comment = (request.POST.get("comment") or "")[: polls.MAX_COMMENT]
        try:
            polls.vote(poll, resident, request.POST.get("option"), comment)
        except VoteRefused as refused:
            error = str(refused)
            status = 400 if polls.is_open(poll) else 409
        else:
            thanks, comment = VOTE_THANKS, ""
        if delivery.read_at is None:
            Delivery.objects.filter(pk=delivery.pk).update(read_at=_start_of_today())
    return _private(
        render(
            request,
            "messaging/reply.html",
            {
                "campaign": campaign,
                "delivery": delivery,
                "poll": poll,
                "voted": polls.has_voted(poll, resident),
                "open": polls.is_open(poll),
                "thanks": thanks,
                "error": error,
                "comment": comment,
            },
            status=status,
        )
    )


@login_required
@sensitive_post_parameters("option", "comment")
@require_http_methods(["GET", "POST"])
def message(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    # Same messages as the inbox (not a campaign cancelled afterwards).
    delivery = inbox.received(request.user).filter(campaign=campaign).first()
    if delivery is None:
        raise Http404
    poll = poll_of(campaign)
    is_open = replies.is_open(campaign)
    error = comment = ""
    status = 200
    if request.method == "POST" and poll is not None:
        comment = (request.POST.get("comment") or "")[: polls.MAX_COMMENT]
        try:
            polls.vote(poll, request.user, request.POST.get("option"), comment)
        except VoteRefused as refused:
            # Shown on the page itself, with the comment kept.
            error = str(refused)
            status = 400 if polls.is_open(poll) else 409
        else:
            messages.success(request, VOTE_THANKS)
            return redirect("inbox:message", pk=campaign.pk)
    if request.method == "POST" and poll is None:
        answer = request.POST.get("answer", "")
        if not is_open:
            messages.warning(request, "Les réponses à ce message sont fermées.")
        elif answer not in THANKS:
            messages.warning(request, INVALID)
        else:
            replies.record(campaign, request.user, answer)
            messages.success(request, THANKS[answer])
        return redirect("inbox:message", pk=campaign.pk)
    if delivery.read_at is None:
        Delivery.objects.filter(pk=delivery.pk).update(read_at=timezone.now())
    response = render(
        request,
        "messaging/message.html",
        {
            "active_nav": "messages",
            "campaign": campaign,
            "short_type": inbox.SHORT_TYPES.get(campaign.type, "Message"),
            "delivery": delivery,
            "current": AttendanceReply.objects.filter(
                campaign=campaign, resident=request.user
            ).first(),
            "asks": campaign.reply_type == "attendance",
            "closed": not is_open,
            "closes_at": replies.closes_at(campaign),
            "poll": poll,
            "voted": poll is not None and polls.has_voted(poll, request.user),
            "open": poll is not None and polls.is_open(poll),
            "error": error,
            "comment": comment,
        },
        status=status,
    )
    add_never_cache_headers(response)
    return response


@login_required
@require_safe
def inbox_list(request):
    if not is_resident(request.user):
        return redirect("home")  # the staff have their own pages
    key = request.GET.get("show", "all")
    if key not in inbox.FILTER_KEYS:
        key = "all"
    page = Paginator(inbox.inbox(request.user, key), PER_PAGE).get_page(request.GET.get("page"))
    current = next(item for item in inbox.FILTERS if item.key == key)
    unread = inbox.unread_count(request.user, key)
    total = unread if key == "all" else inbox.unread_count(request.user)
    response = render(
        request,
        "messaging/inbox.html",
        {
            "active_nav": "messages",
            "filters": inbox.FILTERS,
            "current": current,
            "page_obj": page,
            "items": inbox.items(request.user, page.object_list),
            "unread": unread,
            # Talks with the educators live here too (design card D2).
            "conversations": direct.with_unread(
                direct.resident_conversations(request.user).select_related("educator"),
                request.user,
            ).order_by("-updated_at"),
            # Replaces the context processor: no second count for the bar.
            "unread_messages": total,
        },
    )
    add_never_cache_headers(response)
    return response


@login_required
@require_POST
def read_all(request):
    key = request.POST.get("show", "all")
    if key not in inbox.FILTER_KEYS:
        key = "all"
    count = inbox.mark_all_read(request.user, key)
    if count:
        s = "s" if count > 1 else ""
        messages.success(request, f"{count} message{s} marqué{s} comme lu{s}.")
    url = reverse("inbox:list")
    if key != "all":
        url += f"?show={key}"
    return redirect(url)
