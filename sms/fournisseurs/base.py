"""Interface commune des fournisseurs de SMS.

Chaque fournisseur reçoit ses OPTIONS (réglage ``SMS``) en arguments nommés
et implémente ``envoyer(numero, texte)``. Le reste de l'application ne
connaît que cette interface : changer de fournisseur ne change que le réglage.
"""

from dataclasses import dataclass


class ErreurSms(Exception):
    """Erreur générale d'envoi de SMS."""


class ErreurConfiguration(ErreurSms):
    """Le fournisseur est mal configuré (identifiant manquant…)."""


class ErreurEnvoi(ErreurSms):
    """Le fournisseur a refusé ou n'a pas pu envoyer le SMS.

    ``temporaire`` : vrai si un nouvel essai plus tard peut réussir (réseau,
    surcharge). Faux si le même envoi échouera encore (numéro refusé,
    identifiants faux). Les relances (carte T21) s'en servent.
    """

    def __init__(self, message, *, temporaire):
        super().__init__(message)
        self.temporaire = temporaire


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
