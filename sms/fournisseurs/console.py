"""Fournisseur de développement : le SMS est écrit dans la console, rien n'est envoyé."""

import sys
import uuid

from ..segments import analyser
from .base import FournisseurSms, ResultatEnvoi


class FournisseurConsole(FournisseurSms):
    nom = "console"

    def envoyer(self, numero, texte):
        info = analyser(texte)
        flux = self.options.get("flux") or sys.stdout
        flux.write(
            f"--- SMS à {numero} ({info.encodage}, {info.segments} segment"
            f"{'s' if info.segments > 1 else ''}) ---\n{texte}\n---\n"
        )
        flux.flush()
        return ResultatEnvoi(self.nom, uuid.uuid4().hex)
