"""Fournisseur des tests : les SMS sont gardés en mémoire, dans ``boite``.

Le lanceur de tests du projet (outils/lanceur_tests.py) le règle pour chaque
test, comme Django le fait pour les e-mails (``mail.outbox``) : aucun test ne
peut envoyer un vrai SMS.
"""

import uuid
from dataclasses import dataclass

from .base import FournisseurSms, ResultatEnvoi


@dataclass(frozen=True)
class SmsEnvoye:
    numero: str
    texte: str
    identifiant: str


boite = []


class FournisseurMemoire(FournisseurSms):
    nom = "memoire"

    def envoyer(self, numero, texte):
        identifiant = uuid.uuid4().hex
        boite.append(SmsEnvoye(numero, texte, identifiant))
        return ResultatEnvoi(self.nom, identifiant)
