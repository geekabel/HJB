"""Decorator for sensitive actions: passkey used less than 10 minutes ago."""

from functools import wraps
from urllib.parse import urlencode

from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect
from django.urls import reverse

from .session_policy import confirmed_recently


def recent_confirmation_required(view):
    """Otherwise, the person goes through /connexion/confirmer/ and then comes back here."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not confirmed_recently(request):
            params = urlencode({"next": request.get_full_path()})
            return redirect(f"{reverse('access:confirm')}?{params}")
        return view(request, *args, **kwargs)

    return wrapper
