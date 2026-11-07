"""Login, confirmation and logout pages (cards T13 and T14c)."""

import hashlib

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
from accounts.roles import GROUP_BY_ROLE, Role
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
TOO_MANY_APP_CODES = "Trop d'essais depuis ce réseau. Réessayez dans 10 minutes."
# Wrong tries only (a right code never counts), over 10 minutes. Per address
# and username: a stranger cannot block everyone behind the residence wifi.
# Per address: a higher ceiling against a bot trying many usernames.
MAX_APP_CODE_FAILURES = 10
MAX_APP_CODE_FAILURES_PER_ADDRESS = 100
APP_CODE_WINDOW = 10 * 60


def _waiting_message(waiting):
    return (
        f"Code juste, mais il y a eu des essais faux sur ce compte. "
        f"Réessayez dans {waiting.minutes} minute{'s' if waiting.minutes > 1 else ''}."
    )


def _limit_keys(ip, username):
    tag = hashlib.sha256(username.casefold().encode()).hexdigest()[:16]
    return [
        (f"app_code:{tag}", MAX_APP_CODE_FAILURES),
        ("app_code", MAX_APP_CODE_FAILURES_PER_ADDRESS),
    ]


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
        username = form.cleaned_data["username"].strip()
        limits = _limit_keys(ip, username)
        if any(rate_limits.limit_reached(name, ip, most) for name, most in limits):
            form.add_error(None, TOO_MANY_APP_CODES)
        else:
            user = User.objects.filter(username=username).first()
            device = app_code.device_of(user) if app_code.allowed(user) else None
            try:
                if device is None:
                    app_code.same_work_without_device()
                    right = False
                else:
                    right = app_code.verify(device, form.cleaned_data["code"], request)
            except app_code.Waiting as waiting:
                form.add_error(None, _waiting_message(waiting))
            else:
                if right:
                    login(request, user, backend="accounts.backends.PermissionsOnlyBackend")
                    otp_login(request, device)
                    session_policy.open_session(request, user)
                    return redirect(next_url or settings.LOGIN_REDIRECT_URL)
                for name, _most in limits:
                    rate_limits.record_attempt(name, ip, APP_CODE_WINDOW)
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
        try:
            right = app_code.verify(device, form.cleaned_data["code"], request)
        except app_code.Waiting as waiting:
            form.add_error("code", _waiting_message(waiting))
        else:
            if right:
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
def account(request):
    """Mon compte: how I log in, notifications, installation, logout (design card D1)."""
    user = request.user
    staff = not is_resident(user)
    passkeys = list(get_credential_model().objects.filter(user=user).order_by("-created_at"))
    return render(
        request,
        "access/account.html",
        {
            "layout": "ui/staff.html" if staff else "ui/resident.html",
            "active_nav": "account",
            "passkey": passkeys[0] if passkeys else None,
            "other_passkeys": len(passkeys) - 1 if passkeys else 0,
            "app_code": app_code.device_of(user) if app_code.allowed(user) else None,
            "devices": user.push_subscriptions.count(),
        },
    )


@never_cache
@login_required
def home(request):
    """Home page. Staff start on their main task: meetings for an educator,
    reports for maintenance, residents otherwise.

    The resident home is card T34; the staff dashboard comes with T35.
    """
    user = request.user
    if not is_resident(user):
        # Never the resident home for a staff member (Maintenance included).
        if user.groups.filter(name=GROUP_BY_ROLE[Role.EDUCATOR]).exists() and user.has_perm(
            "accounts.manage_appointments"
        ):
            return redirect("appointments:availability")
        # Maintenance starts on the reports board (card T31).
        if user.groups.filter(name=GROUP_BY_ROLE[Role.MAINTENANCE]).exists() and user.has_perm(
            "accounts.manage_reports"
        ):
            return redirect("reports_staff:board")
        if user.has_perm("accounts.view_residents"):
            return redirect("residents:list")
        if user.has_perm("accounts.send_messages"):
            return redirect("messaging:list")
        return redirect("account")
    from appointments import direct
    from housing.services import current_stay

    from .home import SHOWN, latest_announcement, open_reports, todos

    unread_direct = direct.unread_count(user)
    found = todos(user, unread_direct)
    stay = current_stay(user)
    return render(
        request,
        "access/home.html",
        {
            # Card T34: the first thing to do leads the page, the others follow.
            "lead": found[0] if found else None,
            "todos": found[1:SHOWN],
            "more_todos": len(found) - SHOWN,
            "room": stay.room if stay else None,
            "my_reports": open_reports(user),
            "announcement": latest_announcement(user),
            "active_nav": "home",
            # Replaces the context processor: counted once for the page and the bar.
            "unread_direct": unread_direct,
        },
    )
