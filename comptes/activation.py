"""Codes d'activation (carte T11).

À l'accueil, quand la personne se présente, l'équipe génère un code. La
personne le saisit sur /activer/, puis vérifie son téléphone (T12) et crée sa
clé d'accès (T13).

- Le code est montré une seule fois. En base, on garde son empreinte HMAC
  (clé dérivée de SECRET_KEY) : on peut retrouver le code saisi, mais pas
  relire un code à partir de la base.
- Usage unique, valable 72 h ; un nouveau code annule le précédent.
- Les codes inconnus sont comptés par adresse IP : au-delà de
  ECHECS_MAX en une heure, la saisie est bloquée.

Docs Python : hmac, secrets (https://docs.python.org/3/library/secrets.html).
"""

import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from journal.models import Action
from journal.service import journaliser

from .models import CodeActivation, EchecActivation

# Sans I, L, O, U, 0 ni 1 : rien à confondre en lisant un code imprimé.
ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"
LONGUEUR = 10  # 30^10 : environ 2^49 codes possibles
DUREE_VALIDITE = timedelta(hours=72)
ECHECS_MAX = 10
FENETRE_ECHECS = timedelta(hours=1)


class ErreurActivation(Exception):
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


def normaliser(saisie):
    """« abcde fghjk » ou « ABCDE-FGHJK » deviennent « ABCDEFGHJK »."""
    return "".join(c for c in (saisie or "").upper() if c.isalnum())


def formater(code):
    """« ABCDEFGHJK » devient « ABCDE-FGHJK », plus facile à lire et à recopier."""
    return f"{code[:5]}-{code[5:]}"


def empreinte(code):
    cle = hashlib.sha256(b"hjb.code-activation:" + settings.SECRET_KEY.encode()).digest()
    return hmac.new(cle, normaliser(code).encode(), hashlib.sha256).hexdigest()


def generer_code(utilisateur, *, par=None, requete=None):
    """Crée un code pour ``utilisateur`` et le renvoie en clair, formaté.

    Les codes encore valides de cette personne sont annulés.
    """
    maintenant = timezone.now()
    for _ in range(5):  # une collision d'empreinte est très improbable ; on réessaie
        code = "".join(secrets.choice(ALPHABET) for _ in range(LONGUEUR))
        try:
            with transaction.atomic():
                CodeActivation.objects.valides().filter(utilisateur=utilisateur).update(
                    annule_le=maintenant
                )
                code_activation = CodeActivation.objects.create(
                    utilisateur=utilisateur,
                    empreinte=empreinte(code),
                    cree_par=par,
                    expire_le=maintenant + DUREE_VALIDITE,
                )
                journaliser(
                    Action.CODE_ACTIVATION_GENERE,
                    acteur=par,
                    cible=utilisateur,
                    details={"expire_le": code_activation.expire_le.isoformat()},
                    requete=requete,
                )
        except IntegrityError:
            continue
        return formater(code)
    raise RuntimeError("Impossible de générer un code unique.")


def trop_d_echecs(adresse_ip):
    depuis = timezone.now() - FENETRE_ECHECS
    return EchecActivation.objects.filter(adresse_ip=adresse_ip, cree_le__gte=depuis).count() >= (
        ECHECS_MAX
    )


def utiliser_code(saisie, adresse_ip=None):
    """Vérifie le code saisi et le marque comme utilisé. Renvoie le CodeActivation.

    Lève ErreurActivation (code « trop_essais » ou « invalide »).
    """
    if trop_d_echecs(adresse_ip):
        raise ErreurActivation(
            "Trop d'essais. Réessayez dans une heure, ou passez à l'accueil.", "trop_essais"
        )
    code = normaliser(saisie)
    trouve = None
    if len(code) == LONGUEUR:
        trouve = (
            CodeActivation.objects.valides()
            .filter(empreinte=empreinte(code), utilisateur__is_active=True)
            .select_related("utilisateur")
            .first()
        )
    # Usage unique, même si deux appareils envoient le code au même moment.
    if trouve is None or not CodeActivation.objects.filter(
        pk=trouve.pk, utilise_le__isnull=True
    ).update(utilise_le=timezone.now()):
        EchecActivation.objects.create(adresse_ip=adresse_ip)
        # Ménage : les échecs de plus d'un jour ne servent plus.
        EchecActivation.objects.filter(cree_le__lt=timezone.now() - timedelta(days=1)).delete()
        raise ErreurActivation(
            "Ce code ne marche pas. Vérifiez-le, ou demandez un nouveau code à l'accueil.",
            "invalide",
        )
    return trouve


def etat_activation(utilisateur):
    """Dernier code et son état, pour la fiche (« actif », « utilise », « expire », None)."""
    dernier = utilisateur.codes_activation.select_related("cree_par").first()
    if dernier is None:
        return None, None
    if dernier.utilise_le:
        return dernier, "utilise"
    if dernier.annule_le or dernier.expire_le <= timezone.now():
        return dernier, "expire"
    return dernier, "actif"


def envoyer_code_par_sms(utilisateur, adresse, *, par=None, requete=None):
    """Génère un code et l'envoie par SMS. Renvoie True si le SMS est parti.

    ``adresse`` : l'adresse absolue de la page d'activation. Si l'envoi échoue
    sans doute possible, le code est annulé : la fiche reste juste.
    """
    from sms.fournisseurs.base import ErreurSms
    from sms.service import envoyer_sms

    if not utilisateur.telephone:
        return False
    code = generer_code(utilisateur, par=par, requete=requete)
    texte = (
        f"Habitat Jeunes Belfort : activez votre compte sur {adresse}#{code} "
        f"(code {code}, valable 72 h, une seule fois)."
    )
    try:
        envoyer_sms(utilisateur.telephone, texte)
    except ErreurSms as erreur:
        if not erreur.incertain:
            CodeActivation.objects.valides().filter(utilisateur=utilisateur).update(
                annule_le=timezone.now()
            )
            return False
    return True
