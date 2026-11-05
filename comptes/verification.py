"""Vérification du téléphone par code SMS (carte T12).

Après le code d'activation, la personne reçoit un code à 6 chiffres sur le
numéro donné à l'accueil. Le saisir prouve qu'elle a ce téléphone.

- Code tiré avec ``secrets``, gardé seulement sous forme d'empreinte HMAC.
- Valable 10 minutes, 5 essais au plus (compteur mis à jour en base de façon
  conditionnelle : deux envois simultanés ne donnent pas un essai de plus).
- Un nouvel envoi au plus toutes les 60 secondes, 3 par heure ; au-delà,
  la personne passe à l'accueil.
"""

import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import VerificationTelephone

DUREE = timedelta(minutes=10)
ESSAIS_MAX = 5
DELAI_RENVOI = timedelta(seconds=60)
ENVOIS_PAR_HEURE = 3


class ErreurVerification(Exception):
    def __init__(self, message, code, **details):
        super().__init__(message)
        self.code = code
        self.details = details


def _empreinte(verification_id, code):
    cle = hashlib.sha256(b"hjb.code-sms:" + settings.SECRET_KEY.encode()).digest()
    message = f"{verification_id}:{code}".encode()
    return hmac.new(cle, message, hashlib.sha256).hexdigest()


def derniere(utilisateur):
    return utilisateur.verifications_telephone.first()


def renvoi_possible_le(utilisateur):
    """Heure à partir de laquelle un nouveau code peut être demandé (None : tout de suite)."""
    precedente = derniere(utilisateur)
    if precedente is None or precedente.cree_le + DELAI_RENVOI <= timezone.now():
        return None
    return precedente.cree_le + DELAI_RENVOI


def attente_avant_renvoi(utilisateur):
    """Secondes à attendre avant de pouvoir demander un nouveau code (0 si possible)."""
    precedente = derniere(utilisateur)
    if precedente is None:
        return 0
    reste = (precedente.cree_le + DELAI_RENVOI - timezone.now()).total_seconds()
    return max(0, int(reste + 0.999))


def envoyer_code(utilisateur):
    """Envoie un nouveau code par SMS. Renvoie la VerificationTelephone.

    Lève ErreurVerification : « sans_numero », « trop_tot », « trop_d_envois », « sms ».
    """
    from sms.fournisseurs.base import ErreurSms
    from sms.service import envoyer_sms

    if not utilisateur.telephone:
        raise ErreurVerification(
            "Aucun numéro n'est enregistré pour vous. Passez à l'accueil pour le donner.",
            "sans_numero",
        )
    code = f"{secrets.randbelow(10**6):06d}"
    with transaction.atomic():
        # Verrou sur la ligne du compte : des demandes simultanées passent une par une,
        # et les limites (60 s, 3 par heure) tiennent même avec des clics en rafale.
        type(utilisateur).objects.select_for_update().get(pk=utilisateur.pk)
        attente = attente_avant_renvoi(utilisateur)
        if attente:
            raise ErreurVerification(
                f"Patientez {attente} secondes avant de demander un nouveau code.",
                "trop_tot",
                attente=attente,
            )
        maintenant = timezone.now()
        recents = utilisateur.verifications_telephone.filter(
            cree_le__gte=maintenant - timedelta(hours=1)
        )
        if recents.count() >= ENVOIS_PAR_HEURE:
            raise ErreurVerification(
                "Trop de codes envoyés. Réessayez dans une heure, ou passez à l'accueil.",
                "trop_d_envois",
            )
        # Un seul code à la fois : les précédents expirent.
        utilisateur.verifications_telephone.filter(
            verifie_le__isnull=True, expire_le__gt=maintenant
        ).update(expire_le=maintenant)
        verification = VerificationTelephone.objects.create(
            utilisateur=utilisateur,
            telephone=utilisateur.telephone,
            empreinte="",
            expire_le=maintenant + DUREE,
        )
        verification.empreinte = _empreinte(verification.pk, code)
        verification.save(update_fields=["empreinte"])

    texte = (
        f"Habitat Jeunes Belfort : votre code de vérification est {code}. "
        "Il expire dans 10 minutes. Ne le donnez à personne."
    )
    try:
        envoyer_sms(utilisateur.telephone, texte)
    except ErreurSms as erreur:
        if not erreur.incertain:
            # Le SMS n'est pas parti : ce code ne peut pas servir. L'envoi compte quand
            # même dans la limite horaire, pour ne pas épuiser le crédit SMS.
            VerificationTelephone.objects.filter(pk=verification.pk).update(expire_le=maintenant)
            raise ErreurVerification(
                "Le SMS n'a pas pu partir. Réessayez dans une minute, ou passez à l'accueil.",
                "sms",
            ) from erreur
    return verification


def verifier_code(utilisateur, saisie):
    """Vérifie le code saisi. Renvoie la VerificationTelephone réussie.

    Lève ErreurVerification : « aucun », « trop_essais », « incorrect ».
    """
    code = "".join(c for c in (saisie or "") if c.isdigit())
    verification = (
        utilisateur.verifications_telephone.filter(
            verifie_le__isnull=True,
            expire_le__gt=timezone.now(),
            telephone=utilisateur.telephone,  # le numéro a pu changer depuis l'envoi
        )
        .order_by("-cree_le", "-id")
        .first()
    )
    if verification is None:
        raise ErreurVerification("Ce code a expiré. Demandez-en un nouveau.", "aucun")
    # Un essai de plus, seulement s'il en reste : vrai même avec deux envois simultanés.
    if not VerificationTelephone.objects.filter(
        pk=verification.pk, tentatives__lt=ESSAIS_MAX
    ).update(tentatives=F("tentatives") + 1):
        raise ErreurVerification(
            "Trop d'essais pour ce code. Demandez-en un nouveau.", "trop_essais"
        )
    verification.refresh_from_db(fields=["tentatives"])
    if len(code) != 6 or not hmac.compare_digest(
        _empreinte(verification.pk, code), verification.empreinte
    ):
        restants = ESSAIS_MAX - verification.tentatives
        if restants <= 0:
            raise ErreurVerification(
                "Code incorrect, et c'était le dernier essai. Demandez un nouveau code.",
                "trop_essais",
            )
        raise ErreurVerification(
            f"Code incorrect. Il vous reste {restants} essai{'s' if restants > 1 else ''}.",
            "incorrect",
            restants=restants,
        )
    maintenant = timezone.now()
    with transaction.atomic():
        if not VerificationTelephone.objects.filter(
            pk=verification.pk, verifie_le__isnull=True
        ).update(verifie_le=maintenant):
            raise ErreurVerification("Ce code a déjà servi.", "aucun")
        # On garde le numéro vérifié : s'il change ensuite, il n'est plus vérifié.
        utilisateur.telephone_verifie = verification.telephone
        utilisateur.telephone_verifie_le = maintenant
        utilisateur.save(update_fields=["telephone_verifie", "telephone_verifie_le"])
    return verification
