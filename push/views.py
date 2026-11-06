"""Notification settings of a person, and the calls of ui/js/push.js (card T19)."""

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from .models import PushSubscription
from .services import endpoint_allowed, keys_valid, save_subscription, send_to_user
from .signals import CHECKED_KEY, SESSION_KEY
from .vapid import application_server_key

TEST_DELAY = 60  # seconds between two test notifications of the same person
MAX_BODY = 4096  # bytes of a subscription sent by the browser


def _layout(user):
    """(template, active menu entry): the staff keep their menu."""
    if user.has_perm("accounts.access_staff_area"):
        return "ui/staff.html", "notifications"
    return "ui/resident.html", "account_section"


@require_GET
@login_required
def settings_page(request):
    try:
        public_key = application_server_key()
    except ImproperlyConfigured:
        public_key = ""
    layout, active_nav = _layout(request.user)
    return render(
        request,
        "push/settings.html",
        {
            "layout": layout,
            "active_nav": active_nav,
            "public_key": public_key,
            "devices": request.user.push_subscriptions.all(),
        },
    )


def _error(message, status=400):
    return JsonResponse({"error": message}, status=status)


@require_POST
@login_required
def subscribe(request):
    """Called by push.js with the PushSubscription of the browser (JSON).

    "mode": "enable" after a tap on the button: the device is recorded for
    this person. "sync" on the other pages: only refreshes a device already
    recorded for this person, never adds one (a shared phone does not start
    receiving the notifications of the next person who logs in).
    """
    if len(request.body) > MAX_BODY:
        return _error("too large", 413)
    try:
        data = json.loads(request.body)
        endpoint = data["endpoint"]
        keys = data["keys"]
        p256dh, auth = keys["p256dh"], keys["auth"]
        mode = data.get("mode", "sync")
    except (ValueError, KeyError, TypeError):
        return _error("invalid subscription")
    if not all(isinstance(v, str) for v in (endpoint, p256dh, auth, mode)):
        return _error("invalid subscription")
    if not endpoint_allowed(endpoint):
        return _error("unknown push service")
    if not (len(p256dh) <= 128 and len(auth) <= 64 and keys_valid(p256dh, auth)):
        return _error("invalid keys")
    # The base page asks once per session (base.html, app.js).
    request.session[CHECKED_KEY] = True
    if mode == "enable":
        save_subscription(
            request.user,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            user_agent=request.headers.get("User-Agent", ""),
        )
        messages.success(request, "Notifications activées sur cet appareil.")
    else:
        # This browser now serves this account: the previous person of a shared
        # phone stops receiving here, even if their session just expired.
        PushSubscription.objects.filter(endpoint=endpoint).exclude(user=request.user).delete()
        updated = PushSubscription.objects.filter(user=request.user, endpoint=endpoint).update(
            p256dh=p256dh, auth=auth
        )
        if not updated:
            request.session.pop(SESSION_KEY, None)
            return JsonResponse({"known": False})
    request.session[SESSION_KEY] = endpoint
    return JsonResponse({"known": True})


@require_POST
@login_required
def unsubscribe(request):
    """Called by push.js after the browser unsubscribed this device."""
    try:
        endpoint = json.loads(request.body)["endpoint"]
    except (ValueError, KeyError, TypeError):
        return _error("invalid request")
    if isinstance(endpoint, str):
        PushSubscription.objects.filter(user=request.user, endpoint=endpoint).delete()
    request.session.pop(SESSION_KEY, None)
    request.session[CHECKED_KEY] = True
    return JsonResponse({"known": False})


@require_POST
@login_required
def remove_device(request, pk):
    """Stop the notifications of one device from the list (for example a lost tablet)."""
    device = get_object_or_404(PushSubscription, pk=pk, user=request.user)
    device.delete()
    messages.success(request, f"{device.device or 'Appareil'} : notifications arrêtées.")
    return redirect("push:settings")


@require_POST
@login_required
def send_test(request):
    key = f"push-test:{request.user.pk}"
    if not cache.add(key, True, TEST_DELAY):
        messages.info(request, "Un essai vient de partir. Attendez une minute avant le suivant.")
        return redirect("push:settings")
    try:
        result = send_to_user(
            request.user,
            title="Notification d'essai",
            body="Les notifications de la résidence arrivent bien sur cet appareil.",
            url="/notifications/",
            tag="test",
        )
    except ImproperlyConfigured:
        messages.warning(request, "Les notifications ne sont pas configurées sur le serveur.")
        return redirect("push:settings")
    if result.sent:
        s = "s" if result.sent > 1 else ""
        messages.success(request, f"Essai envoyé à {result.sent} appareil{s}.")
    elif not (result.failed or result.removed):
        messages.info(request, "Aucun appareil n'a activé les notifications.")
    if result.failed or result.removed:
        messages.warning(
            request,
            "L'essai n'a pas pu partir vers un appareil. Réactivez les notifications dessus.",
        )
    return redirect("push:settings")
