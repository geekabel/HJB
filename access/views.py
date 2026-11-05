"""Login, confirmation and logout pages (card T13)."""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render, resolve_url
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from django_otp_webauthn.utils import get_credential_model

from .session_policy import is_resident


def _next_url(request):
    """The "next" URL if it is safe (same site), otherwise an empty string."""
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    if url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return next_url
    return ""


def _passkey_config(request, mode, next_url=""):
    """Data read by passkey.js (json_script tag, no inline script)."""
    return {
        "mode": mode,
        "begin": reverse("access:verify_begin"),
        "complete": reverse("access:verify_complete"),
        "next": next_url,
    }


@never_cache
def login_view(request):
    next_url = _next_url(request)
    if request.user.is_authenticated:
        return redirect(next_url or settings.LOGIN_REDIRECT_URL)
    return render(
        request,
        "access/login.html",
        {"config": _passkey_config(request, "login", next_url), "next": next_url},
    )


@never_cache
@login_required
def confirm(request):
    """New verification before a sensitive action (see decorators.py)."""
    next_url = _next_url(request) or resolve_url(settings.LOGIN_REDIRECT_URL)
    has_passkey = get_credential_model().objects.filter(user=request.user).exists()
    return render(
        request,
        "access/confirm.html",
        {
            "config": _passkey_config(request, "confirm", next_url),
            "next": next_url,
            "has_passkey": has_passkey,
        },
    )


@require_POST
def logout_view(request):
    logout(request)
    messages.info(request, "Vous êtes déconnecté.")
    return redirect("access:login")


@never_cache
@login_required
def home(request):
    """Temporary home page, to be replaced by cards T34 (residents) and T35 (staff)."""
    user = request.user
    if not is_resident(user) and user.has_perm("accounts.view_residents"):
        return redirect("residents:list")
    passkeys = get_credential_model().objects.filter(user=user).order_by("-created_at")
    return render(request, "access/home.html", {"passkeys": passkeys, "active_nav": "home"})
