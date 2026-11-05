"""Interface commune des fournisseurs de SMS.

Chaque fournisseur reçoit ses OPTIONS (réglage ``SMS``) en arguments nommés
et implémente ``envoyer(numero, texte)``. Le reste de l'application ne
connaît que cette interface : changer de fournisseur ne change que le réglage.
"""

from dataclasses import dataclass


class ErreurSms(Exception):
    """Erreur d'envoi de SMS. Sauf si ``incertain`` est vrai, le SMS n'est pas parti.

    ``temporaire`` : vrai si un nouvel essai plus tard peut réussir (réseau
    coupé avant l'envoi, surcharge). Faux si le même envoi échouera encore.
    ``incertain`` : le fournisseur a peut-être envoyé le SMS (délai dépassé
    pendant la réponse…). Ne jamais relancer automatiquement : risque de
    doublon. Les relances (carte T21) s'appuient sur ces deux indications.
    """

    temporaire = False
    incertain = False


class ErreurConfiguration(ErreurSms):
    """Le fournisseur est mal configuré (identifiant manquant…)."""


class ErreurEnvoi(ErreurSms):
    """Le fournisseur a refusé l'envoi, ou on ne sait pas s'il l'a fait."""

    def __init__(self, message, *, temporaire=False, incertain=False):
        super().__init__(message)
        self.temporaire = temporaire
        self.incertain = incertain


@dataclass(frozen=True)
class ResultatEnvoi:
    fournisseur: str
    identifiant: str  # identifiant du message chez le fournisseur, pour suivre sa livraison


class FournisseurSms:
    nom = "?"
    # Options obligatoires : vérifiées par le contrôle de configuration (sms/checks.py).
    options_obligatoires = ()

    def __init__(self, **options):
        self.options = options

    def options_manquantes(self):
        return [nom for nom in self.options_obligatoires if not self.options.get(nom)]

    def envoyer(self, numero, texte):
        """Envoie ``texte`` au numéro E.164 ``numero``. Renvoie un ResultatEnvoi.

        Lève ErreurEnvoi si le SMS n'est pas parti.
        """
        raise NotImplementedError
