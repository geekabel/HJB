"""Pages of the residents for the messages (cards T22, T23).

- reply(): the personal link of the SMS and of the notification buttons. No
  session: the signed link is the proof. A GET only shows the page (SMS apps
  open links to make a preview); only the buttons (POST) record an answer.
- message(): one message in the application, with the same buttons.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.cache import add_never_cache_headers
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from accounts.models import User

from . import replies
from .models import AttendanceReply, Campaign, Delivery

THANKS = {
    "present": "C'est noté : vous serez présent. Merci !",
    "absent": "C'est noté : vous serez absent. Merci de l'avoir dit.",
}


INVALID = "Choisissez « Présent » ou « Absent »."


def _delivery(campaign, user, failed_too=False):
    deliveries = Delivery.objects.filter(
        campaign=campaign, recipient=user, kind=Delivery.Kind.MESSAGE
    )
    if not failed_too:
        deliveries = deliveries.exclude(status=Delivery.Status.FAILED)
    return deliveries.first()


def _private(response):
    add_never_cache_headers(response)
    # The address holds the personal link: never sent to another site.
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex"
    return response


# The link is the proof, not a session cookie: no CSRF token is needed, and the
# buttons of a notification can answer without opening the application.
@csrf_exempt
@require_http_methods(["GET", "POST"])
def reply(request, token):
    found = replies.read_token(token)
    if found is None:
        raise Http404
    campaign = Campaign.objects.filter(pk=found[0]).first()
    resident = User.objects.filter(pk=found[1], is_active=True).first()
    # A failed delivery too: an SMS marked uncertain may have arrived, and the
    # signed link proves that we sent it to this person.
    delivery = _delivery(campaign, resident, failed_too=True) if campaign and resident else None
    if delivery is None:
        raise Http404
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


@login_required
@require_http_methods(["GET", "POST"])
def message(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    delivery = _delivery(campaign, request.user)
    if delivery is None:
        raise Http404
    is_open = replies.is_open(campaign)
    if request.method == "POST":
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
            "delivery": delivery,
            "current": AttendanceReply.objects.filter(
                campaign=campaign, resident=request.user
            ).first(),
            "asks": campaign.reply_type == "attendance",
            "closed": not is_open,
            "closes_at": replies.closes_at(campaign),
        },
    )
    add_never_cache_headers(response)
    return response
