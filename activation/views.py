"""Activation du compte, côté résident (maquette R0).

Étape 1 : code remis à l'accueil (T11). Étape 2 : téléphone (T12).
Étape 3 : clé d'accès (T13).
"""

import time

from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache

from comptes import verification
from comptes.activation import ErreurActivation, utiliser_code
from journal.service import adresse_ip

from . import parcours
from .forms import FormulaireCode, FormulaireCodeSms

# Échecs de saisie dans ce navigateur, sur la dernière heure.
CLE_ECHECS = "activation_echecs"


@never_cache
def saisie(request):
    formulaire = FormulaireCode(request.POST or None)
    if request.method == "POST" and formulaire.is_valid():
        # Heures des échecs de la dernière heure, dans ce navigateur.
        echecs = [h for h in request.session.get(CLE_ECHECS, []) if time.time() - h < 3600]
        try:
            code = utiliser_code(formulaire.cleaned_data["code"], adresse_ip(request), len(echecs))
        except ErreurActivation as erreur:
            if erreur.code == "invalide":
                echecs.append(time.time())
            request.session[CLE_ECHECS] = echecs
            formulaire.add_error("code", str(erreur))
        else:
            parcours.demarrer(request, code.utilisateur)
            return redirect("activation:telephone")
    return render(request, "activation/saisie.html", {"formulaire": formulaire, "etape": 1})


@never_cache
def telephone(request):
    """Étape 2 : un code SMS prouve que la personne a bien ce téléphone (carte T12)."""
    personne = parcours.personne_en_cours(request)
    if personne is None:
        messages.info(request, "Pour commencer, saisissez le code remis par l'accueil.")
        return redirect("activation:saisie")
    if parcours.etape_faite(request, "telephone_verifie"):
        return redirect("activation:cle")

    formulaire = FormulaireCodeSms()
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "envoyer":
                verification.envoyer_code(personne)
                messages.success(request, "Code envoyé. Il peut mettre une minute à arriver.")
                return redirect("activation:telephone")
            if action == "verifier":
                formulaire = FormulaireCodeSms(request.POST)
                if formulaire.is_valid():
                    verification.verifier_code(personne, formulaire.cleaned_data["code"])
                    parcours.noter(request, "telephone_verifie", True)
                    return redirect("activation:cle")
        except verification.ErreurVerification as erreur:
            if action == "verifier":
                formulaire.add_error("code", str(erreur))
            else:
                messages.warning(request, str(erreur))
                return redirect("activation:telephone")

    derniere = verification.derniere(personne)
    code_envoye = bool(
        derniere
        and derniere.verifie_le is None
        and derniere.expire_le > timezone.now()
        and derniere.telephone == personne.telephone
    )
    return render(
        request,
        "activation/telephone.html",
        {
            "etape": 2,
            "personne": personne,
            "formulaire": formulaire,
            "code_envoye": code_envoye,
            "attente": verification.attente_avant_renvoi(personne),
        },
    )


@never_cache
def mauvais_numero(request):
    """« Ce n'est pas mon numéro » : seul l'accueil peut le corriger."""
    parcours.terminer(request)
    return render(request, "activation/mauvais_numero.html", {"etape": 2})


@never_cache
def cle(request):
    """Étape 3 : clé d'accès (carte T13). En attendant, la vérification est confirmée."""
    personne = parcours.personne_en_cours(request)
    if personne is None or not parcours.etape_faite(request, "telephone_verifie"):
        return redirect("activation:telephone" if personne else "activation:saisie")
    return render(request, "activation/cle.html", {"etape": 3, "personne": personne})
