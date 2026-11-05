"""Resident pages of the housing app: "Mon wifi" (card T16).

The resident sees the network name, the username and the end date of the
access of their room. The password stays masked: it is shown after a passkey
confirmation of less than 10 minutes, and each display goes to the audit log,
as for the staff.
"""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured
from django.shortcuts import redirect, render
from django.utils.cache import add_never_cache_headers
from django.views.decorators.debug import sensitive_variables
from django.views.decorators.http import require_GET

from access.decorators import recent_confirmation_required

from . import wifi
from .models import WifiSettings
from .services import current_stay
from .wifi_crypto import WifiDecryptionError

logger = logging.getLogger(__name__)

CANNOT_SHOW = (
    "Le mot de passe ne peut pas être affiché pour le moment. "
    "Passez à l'accueil, l'équipe vous le donnera."
)


def time_left(days):
    """Short French text for the days left before the end of an access."""
    if days < 0:
        return "expiré"
    if days == 0:
        return "dernier jour"
    if days < 60:
        return f"encore {days} jour{'s' if days > 1 else ''}"
    return f"encore {days // 30} mois"


def validity_percent(access):
    """Share of the validity still left, from 0 to 100 (for the bar)."""
    total = (access.expires_on - access.created_on).days
    if total <= 0:
        return 0
    return max(0, min(100, round(100 * access.days_left / total)))


def _page(request, password=None):
    stay = current_stay(request.user)
    access = wifi.current_access(stay.room) if stay else None
    response = render(
        request,
        "housing/my_wifi.html",
        {
            "active_nav": "home",
            "stay": stay,
            "access": access,
            "network_name": WifiSettings.load().network_name,
            "password": password,
            "time_left": time_left(access.days_left) if access else "",
            "validity_percent": validity_percent(access) if access else 0,
        },
    )
    # The username (and maybe the password) is on the page: never kept in a cache.
    add_never_cache_headers(response)
    return response


@require_GET
@login_required
def my_wifi(request):
    return _page(request)


@sensitive_variables("password")
@require_GET
@login_required
@recent_confirmation_required
def my_wifi_password(request):
    """The same page, with the password shown. Each display goes to the audit log."""
    stay = current_stay(request.user)
    access = wifi.current_access(stay.room) if stay else None
    if access is None:
        return redirect("housing:my_wifi")
    try:
        password = wifi.reveal_password(access, by=request.user, request=request)
    except (WifiDecryptionError, ImproperlyConfigured):
        logger.exception("Could not show the wifi password to the resident")
        messages.warning(request, CANNOT_SHOW)
        return redirect("housing:my_wifi")
    return _page(request, password=password)
