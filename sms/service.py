"""Point d'entrée unique pour envoyer un SMS : ``envoyer_sms(numero, texte)``.

Le fournisseur actif vient du réglage ``SMS`` (même forme que les réglages
d'e-mail de Django) :

    SMS = {"BACKEND": "sms.fournisseurs.ovh.FournisseurOvh", "OPTIONS": {...}}
"""

import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.module_loading import import_string

from comptes.telephone import masquer_telephone, normaliser_telephone, valider_e164

from .fournisseurs.base import ErreurConfiguration, ErreurEnvoi, ErreurSms
from .segments import analyser

journal = logging.getLogger(__name__)

# Au-delà, le message coûte cher et se lit mal sur un téléphone.
SEGMENTS_MAX = 6


def fournisseur_actif():
    reglage = getattr(settings, "SMS", {})
    try:
        classe = import_string(reglage["BACKEND"])
    except (KeyError, ImportError) as erreur:
        raise ErreurConfiguration(f"Réglage SMS invalide : {erreur}") from erreur
    return classe(**reglage.get("OPTIONS", {}))


def envoyer_sms(numero, texte):
    """Envoie un SMS au numéro E.164 ``numero``. Renvoie un ResultatEnvoi.

    Lève ErreurSms (ou une sous-classe) en cas d'échec ; voir ses attributs
    ``temporaire`` et ``incertain`` avant tout nouvel essai.
    """
    try:
        valider_e164(numero)
        # Numéro réel et portable (phonenumbers), pas seulement « + et chiffres ».
        valide = normaliser_telephone(numero) == numero
    except ValidationError:
        valide = False
    if not valide:
        raise ErreurEnvoi("Le numéro n'est pas un portable au format international.")
    texte = (texte or "").strip()
    if not texte:
        raise ErreurEnvoi("Le message est vide.")
    info = analyser(texte)
    if info.segments > SEGMENTS_MAX:
        raise ErreurEnvoi(
            f"Le message est trop long ({info.segments} SMS, {SEGMENTS_MAX} au plus)."
        )

    fournisseur = fournisseur_actif()
    manquantes = fournisseur.options_manquantes()
    if manquantes:
        raise ErreurConfiguration(
            f"Fournisseur {fournisseur.nom} : options manquantes ({', '.join(manquantes)})."
        )
    # Les journaux ne contiennent jamais le numéro complet ni le texte.
    try:
        resultat = fournisseur.envoyer(numero, texte)
    except ErreurSms as erreur:
        journal.warning(
            "Échec d'envoi SMS via %s vers %s : %s",
            fournisseur.nom,
            masquer_telephone(numero),
            erreur,
        )
        raise
    journal.info(
        "SMS envoyé via %s vers %s (%s, %d segment(s), id %s)",
        fournisseur.nom,
        masquer_telephone(numero),
        info.encodage,
        info.segments,
        resultat.identifiant,
    )
    return resultat
