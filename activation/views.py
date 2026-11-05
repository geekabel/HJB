"""Activation du compte, côté résident (maquette R0).

Étape 1 : code remis à l'accueil (T11). Étape 2 : téléphone (T12).
Étape 3 : clé d'accès (T13).
"""

import json
import logging
import time

from django.contrib import messages
from django.contrib.auth import login
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from django_otp import login as otp_login
from django_otp_webauthn.exceptions import OTPWebAuthnApiError
from django_otp_webauthn.utils import get_credential_model, rewrite_exceptions

from comptes import verification
from comptes.activation import ErreurActivation, utiliser_code
from comptes.models import User
from connexion import session
from connexion.erreurs import reponse_erreur
from connexion.webauthn import AideActivation
from journal.models import Action
from journal.service import adresse_ip, journaliser
from residents.depart import cles_de_session, fermer_sessions

from . import parcours
from .forms import FormulaireCode, FormulaireCodeSms

journal_webauthn = logging.getLogger("django_otp_webauthn")

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
            parcours.demarrer(request, code)
            return redirect("activation:telephone")
    return render(request, "activation/saisie.html", {"formulaire": formulaire, "etape": 1})


@never_cache
def telephone(request):
    """Étape 2 : un code SMS prouve que la personne a bien ce téléphone (carte T12)."""
    personne = parcours.personne_en_cours(request)
    if personne is None:
        messages.info(request, "Pour commencer, saisissez le code remis par l'accueil.")
        return redirect("activation:saisie")
    if parcours.etape_faite(request, "telephone_verifie") and personne.telephone_est_verifie:
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
            "renvoi_le": verification.renvoi_possible_le(personne),
        },
    )


@never_cache
def mauvais_numero(request):
    """« Ce n'est pas mon numéro » : seul l'accueil peut le corriger.

    Simple page d'information : un affichage (GET) ne change rien.
    """
    return render(request, "activation/mauvais_numero.html", {"etape": 2})


# État de la cérémonie WebAuthn, gardé dans le parcours entre le début et la fin.
ETAT_CLE = "cle_etat"
BACKEND_CLE = "django_otp_webauthn.backends.WebAuthnBackend"


def _personne_prete(request):
    """La personne du parcours, si son téléphone est vérifié (revérifié à chaque fois)."""
    personne = parcours.personne_en_cours(request)
    if (
        personne is not None
        and parcours.etape_faite(request, "telephone_verifie")
        and personne.telephone_est_verifie
    ):
        return personne
    return None


@never_cache
def cle(request):
    """Étape 3 : création de la clé d'accès (carte T13)."""
    personne = _personne_prete(request)
    if personne is None:
        if parcours.personne_en_cours(request):
            return redirect("activation:telephone")
        return redirect("activation:saisie")
    configuration = {
        "mode": "creation",
        "debut": reverse("activation:cle_debut"),
        "fin": reverse("activation:cle_fin"),
        "suite": "",
    }
    return render(
        request,
        "activation/cle.html",
        {"etape": 3, "personne": personne, "configuration": configuration},
    )


PARCOURS_FINI = (
    "Votre activation a expiré. Recommencez avec le code remis par l'accueil, "
    "ou demandez-en un nouveau."
)


@require_POST
@never_cache
def cle_debut(request):
    """Options de création de la clé, pour navigator.credentials.create()."""
    personne = _personne_prete(request)
    if personne is None:
        return reponse_erreur("parcours", 403, PARCOURS_FINI)
    options, etat = AideActivation(request).register_begin(user=personne)
    parcours.noter(request, ETAT_CLE, etat)
    return JsonResponse(options)


@require_POST
@never_cache
def cle_fin(request):
    """Vérifie et enregistre la clé, remplace les anciennes, puis connecte la personne."""
    etat = parcours.retirer(request, ETAT_CLE)  # usage unique, même en cas d'erreur
    personne = _personne_prete(request)
    if personne is None:
        return reponse_erreur("parcours", 403, PARCOURS_FINI)
    if not etat:
        return reponse_erreur("invalid_state", 400)
    try:
        donnees = json.loads(request.body)
    except ValueError:
        return reponse_erreur("malformed_request", 400)

    try:
        with rewrite_exceptions(logger=journal_webauthn), transaction.atomic():
            # Verrou sur le compte : deux créations simultanées passent l'une après l'autre.
            User.objects.select_for_update().get(pk=personne.pk)
            cle_acces = AideActivation(request).register_complete(
                user=personne, state=etat, data=donnees
            )
            # Récupération (téléphone perdu ou changé) : les anciennes clés ne servent plus.
            anciennes = (
                get_credential_model().objects.filter(user=personne).exclude(pk=cle_acces.pk)
            )
            nombre = anciennes.count()
            anciennes.delete()
            journaliser(
                Action.CLE_ACCES_CREEE,
                acteur=personne,
                cible=personne,
                details={"anciennes_retirees": nombre},
                requete=request,
            )
    except OTPWebAuthnApiError as erreur:
        return reponse_erreur(erreur.code, erreur.status_code)

    # Les autres sessions de la personne (ancien téléphone) sont fermées.
    autres_sessions = cles_de_session(personne)
    login(request, personne, backend=BACKEND_CLE)  # nouvelle clé de session, last_login rempli
    otp_login(request, cle_acces)
    fermer_sessions(autres_sessions)
    parcours.terminer(request)
    session.ouvrir(request, personne)
    return JsonResponse({"id": cle_acces.pk, "redirect_url": reverse("accueil")})
