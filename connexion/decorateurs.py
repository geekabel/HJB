"""Décorateur des actions sensibles : clé d'accès utilisée il y a moins de 10 minutes."""

from functools import wraps
from urllib.parse import urlencode

from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect
from django.urls import reverse

from .session import confirmee_recemment


def confirmation_recente(vue):
    """Sinon, la personne passe par /connexion/confirmer/ puis revient ici."""

    @wraps(vue)
    def enveloppe(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not confirmee_recemment(request):
            parametres = urlencode({"next": request.get_full_path()})
            return redirect(f"{reverse('connexion:confirmer')}?{parametres}")
        return vue(request, *args, **kwargs)

    return enveloppe
