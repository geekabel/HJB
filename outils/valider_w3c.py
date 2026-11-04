"""Valide le HTML capturé et le CSS du projet avec le Nu Html Checker (W3C).

    python -m outils.valider_w3c --jar chemin/vers/vnu.jar --html build/html

- HTML : toutes les pages écrites par ``outils.capture_html`` pendant les tests.
- CSS : tous les fichiers ``.css`` du projet, hors dossiers générés.

Le programme s'arrête avec un code non nul si le validateur signale une erreur.
Documentation du validateur : https://validator.github.io/validator/docs/vnu.1.html
"""

import argparse
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
DOSSIERS_IGNORES = {".git", ".venv", "venv", "node_modules", "staticfiles", "build", "media"}


def fichiers_css(racine=RACINE):
    """Fichiers CSS écrits pour le projet (les dossiers générés sont ignorés)."""
    return sorted(
        chemin
        for chemin in racine.rglob("*.css")
        if not DOSSIERS_IGNORES.intersection(chemin.relative_to(racine).parts)
    )


def valider(jar, arguments):
    commande = ["java", "-jar", str(jar), *arguments]
    return subprocess.run(commande, check=False).returncode


def main(argv=None):
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument("--jar", required=True, type=Path, help="chemin de vnu.jar")
    parseur.add_argument("--html", type=Path, default=RACINE / "build" / "html")
    args = parseur.parse_args(argv)

    erreurs = 0
    pages = sorted(args.html.glob("*.html")) if args.html.is_dir() else []
    if pages:
        print(f"HTML : {len(pages)} page(s) à valider")
        erreurs += valider(args.jar, ["--skip-non-html", str(args.html)])
    else:
        print("HTML : aucune page capturée pour l'instant")

    feuilles = fichiers_css()
    if feuilles:
        print(f"CSS : {len(feuilles)} fichier(s) à valider")
        erreurs += valider(args.jar, ["--css", *map(str, feuilles)])
    else:
        print("CSS : aucun fichier pour l'instant")

    if erreurs:
        print("Le validateur W3C signale des erreurs.", file=sys.stderr)
        return 1
    print("Validation W3C réussie.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
