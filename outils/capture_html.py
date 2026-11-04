"""Enregistre les pages rendues pendant les tests, pour les passer au validateur W3C.

Usage dans un test :

    reponse = self.client.get(url)
    enregistrer_page("accueil-resident", reponse)

Rien n'est écrit tant que la variable d'environnement ``HTML_CAPTURE_DIR``
n'est pas définie : les tests normaux ne touchent pas au disque.
"""

import os
import re
from pathlib import Path


def enregistrer_page(nom, reponse):
    """Écrit le HTML de ``reponse`` dans ``$HTML_CAPTURE_DIR/<nom>.html``."""
    dossier = os.environ.get("HTML_CAPTURE_DIR")
    if not dossier:
        return None
    nom_fichier = re.sub(r"[^a-z0-9-]+", "-", nom.lower()).strip("-") or "page"
    chemin = Path(dossier) / f"{nom_fichier}.html"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes(reponse.content)
    return chemin
