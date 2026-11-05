"""Pages de connexion, de confirmation et de déconnexion (carte T13)."""

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

from .session import est_resident


def _suite(request):
    """L'adresse « next » si elle est sûre (même site), sinon une chaîne vide."""
    suite = request.POST.get("next") or request.GET.get("next") or ""
    if url_has_allowed_host_and_scheme(
        suite, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return suite
    return ""


def _configuration(request, mode, suite=""):
    """Données lues par cle-acces.js (balise json_script, sans script en ligne)."""
    return {
        "mode": mode,
        "debut": reverse("connexion:verification_debut"),
        "fin": reverse("connexion:verification_fin"),
        "suite": suite,
    }


@never_cache
def connexion(request):
    suite = _suite(request)
    if request.user.is_authenticated:
        return redirect(suite or settings.LOGIN_REDIRECT_URL)
    return render(
        request,
        "connexion/connexion.html",
        {"configuration": _configuration(request, "connexion", suite), "suite": suite},
    )


@never_cache
@login_required
def confirmer(request):
    """Nouvelle vérification avant une action sensible (voir decorateurs.py)."""
    suite = _suite(request) or resolve_url(settings.LOGIN_REDIRECT_URL)
    a_une_cle = get_credential_model().objects.filter(user=request.user).exists()
    return render(
        request,
        "connexion/confirmer.html",
        {
            "configuration": _configuration(request, "confirmation", suite),
            "suite": suite,
            "a_une_cle": a_une_cle,
        },
    )


@require_POST
def deconnexion(request):
    logout(request)
    messages.info(request, "Vous êtes déconnecté.")
    return redirect("connexion:connexion")


@never_cache
@login_required
def accueil(request):
    """Accueil provisoire, remplacé par la carte T34 (résidents) et T35 (équipe)."""
    utilisateur = request.user
    if not est_resident(utilisateur) and utilisateur.has_perm("comptes.voir_residents"):
        return redirect("residents:liste")
    cles = get_credential_model().objects.filter(user=utilisateur).order_by("-created_at")
    return render(request, "connexion/accueil.html", {"cles": cles, "actif": "accueil"})
