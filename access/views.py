"""Login, confirmation and logout pages (cards T13 and T14c)."""

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render, resolve_url
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST
from django_otp import login as otp_login
from django_otp_webauthn.utils import get_credential_model

from accounts.models import User
from audit.service import client_ip

from . import app_code, rate_limits, session_policy
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


class AppCodeLoginForm(forms.Form):
    username = forms.CharField(
        label="Identifiant",
        max_length=150,
        widget=forms.TextInput(
            attrs={"autocomplete": "username", "autocapitalize": "none", "spellcheck": "false"}
        ),
    )
    code = forms.CharField(
        label="Code de l'application",
        max_length=12,
        help_text="6 chiffres",
        widget=forms.TextInput(
            attrs={"autocomplete": "one-time-code", "inputmode": "numeric", "class": "code-field"}
        ),
    )


class AppCodeConfirmForm(forms.Form):
    code = AppCodeLoginForm.base_fields["code"]


WRONG_APP_CODE = "Identifiant ou code incorrect. Attendez le code suivant et réessayez."
MAX_APP_CODE_TRIES = 30  # per address, over 10 minutes (each device also slows down)
APP_CODE_WINDOW = 10 * 60


@never_cache
@sensitive_post_parameters("code")
@require_http_methods(["GET", "POST"])
def login_app_code(request):
    """Staff login with the code of an authenticator app (card T14c).

    The same message for an unknown account, a resident, or a wrong code:
    the page never tells which accounts exist.
    """
    next_url = _next_url(request)
    if request.user.is_authenticated:
        return redirect(next_url or settings.LOGIN_REDIRECT_URL)
    form = AppCodeLoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        ip = client_ip(request)
        if rate_limits.limit_reached("app_code", ip, MAX_APP_CODE_TRIES):
            form.add_error(None, "Trop d'essais depuis ce réseau. Réessayez dans 10 minutes.")
        else:
            rate_limits.record_attempt("app_code", ip, APP_CODE_WINDOW)
            user = User.objects.filter(username=form.cleaned_data["username"].strip()).first()
            device = app_code.device_of(user) if app_code.allowed(user) else None
            if device is not None and app_code.verify(device, form.cleaned_data["code"]):
                login(request, user, backend="accounts.backends.PermissionsOnlyBackend")
                otp_login(request, device)
                session_policy.open_session(request, user)
                return redirect(next_url or settings.LOGIN_REDIRECT_URL)
            form.add_error(None, WRONG_APP_CODE)
    return render(request, "access/login_app_code.html", {"form": form, "next": next_url})


@never_cache
@login_required
@sensitive_post_parameters("code")
@require_http_methods(["GET", "POST"])
def confirm(request):
    """New verification before a sensitive action (see decorators.py)."""
    next_url = _next_url(request) or resolve_url(settings.LOGIN_REDIRECT_URL)
    has_passkey = get_credential_model().objects.filter(user=request.user).exists()
    device = app_code.device_of(request.user) if app_code.allowed(request.user) else None
    form = AppCodeConfirmForm(request.POST or None) if device else None
    if request.method == "POST" and form is not None and form.is_valid():
        if app_code.verify(device, form.cleaned_data["code"]):
            otp_login(request, device)
            session_policy.open_session(request, request.user)
            return redirect(next_url)
        form.add_error("code", "Ce code ne correspond pas. Tapez le code affiché maintenant.")
    return render(
        request,
        "access/confirm.html",
        {
            "config": _passkey_config(request, "confirm", next_url),
            "next": next_url,
            "has_passkey": has_passkey,
            "form": form,
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
