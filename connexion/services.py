"""Couper l'accès d'un compte (téléphone perdu ou volé), carte T13."""

from django.db import transaction
from django.utils import timezone
from django_otp_webauthn.utils import get_credential_model

from comptes.models import CodeActivation
from comptes.sessions import cles_de_session, fermer_sessions
from journal.models import Action
from journal.service import journaliser


def couper_acces(utilisateur, *, par=None, requete=None):
    """Supprime les clés d'accès, annule le code en attente et ferme les sessions.

    La personne pourra revenir avec un nouveau code d'activation (et, si sa
    puce est perdue, un numéro de téléphone corrigé sur sa fiche).
    Renvoie (clés supprimées, sessions fermées).
    """
    sessions = cles_de_session(utilisateur)
    with transaction.atomic():
        type(utilisateur).objects.select_for_update().get(pk=utilisateur.pk)
        cles = get_credential_model().objects.filter(user=utilisateur)
        nombre_cles = cles.count()
        cles.delete()
        CodeActivation.objects.valides().filter(utilisateur=utilisateur).update(
            annule_le=timezone.now()
        )
        nombre_sessions = fermer_sessions(sessions)
        journaliser(
            Action.ACCES_COUPE,
            acteur=par,
            cible=utilisateur,
            details={"cles_retirees": nombre_cles, "sessions_fermees": nombre_sessions},
            requete=requete,
        )
    return nombre_cles, nombre_sessions
