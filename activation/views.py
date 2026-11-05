"""Activation du compte, côté résident (maquette R0).

Étape 1 : code remis à l'accueil (T11). Étape 2 : téléphone (T12).
Étape 3 : clé d'accès (T13).
"""

from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache

from comptes.activation import ErreurActivation, utiliser_code
from journal.service import adresse_ip

from . import parcours
from .forms import FormulaireCode


@never_cache
def saisie(request):
    formulaire = FormulaireCode(request.POST or None)
    if request.method == "POST" and formulaire.is_valid():
        try:
            code = utiliser_code(formulaire.cleaned_data["code"], adresse_ip(request))
        except ErreurActivation as erreur:
            formulaire.add_error("code", str(erreur))
        else:
            parcours.demarrer(request, code.utilisateur)
            return redirect("activation:telephone")
    return render(request, "activation/saisie.html", {"formulaire": formulaire, "etape": 1})


@never_cache
def telephone(request):
    """Étape 2 : vérification du téléphone (carte T12)."""
    personne = parcours.personne_en_cours(request)
    if personne is None:
        messages.info(request, "Pour commencer, saisissez le code remis par l'accueil.")
        return redirect("activation:saisie")
    return render(request, "activation/telephone.html", {"personne": personne, "etape": 2})
