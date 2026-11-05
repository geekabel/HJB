"""Aucun fournisseur : tout envoi est refusé.

C'est le réglage de la production tant que DJANGO_SMS_FOURNISSEUR n'est pas
rempli. Contrairement à la console, rien n'est écrit : les numéros et les
textes (codes, mots de passe wifi) ne finissent pas dans les journaux du
serveur.
"""

from .base import ErreurConfiguration, FournisseurSms


class FournisseurAucun(FournisseurSms):
    nom = "aucun"

    def envoyer(self, numero, texte):
        raise ErreurConfiguration(
            "Aucun fournisseur de SMS n'est configuré (variable DJANGO_SMS_FOURNISSEUR)."
        )
