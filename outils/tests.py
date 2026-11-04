import io
import os
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from django.http import HttpResponse
from django.test import SimpleTestCase

from .capture_html import enregistrer_page
from .valider_w3c import fichiers_css, main


class CaptureHtmlTests(SimpleTestCase):
    def test_ne_fait_rien_sans_dossier_de_capture(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(enregistrer_page("accueil", HttpResponse("<p>x</p>")))

    def test_ecrit_la_page_avec_un_nom_de_fichier_sur(self):
        with tempfile.TemporaryDirectory() as dossier:
            with mock.patch.dict(os.environ, {"HTML_CAPTURE_DIR": dossier}):
                chemin = enregistrer_page("Accueil / Résident", HttpResponse("<p>x</p>"))
            self.assertEqual(chemin.name, "accueil-r-sident.html")
            self.assertEqual(chemin.read_bytes(), b"<p>x</p>")


class ValidationW3CTests(SimpleTestCase):
    def test_ignore_le_css_des_dossiers_generes(self):
        with tempfile.TemporaryDirectory() as dossier:
            racine = Path(dossier)
            for relatif in ("static/css/site.css", "staticfiles/admin/base.css", ".venv/x.css"):
                (racine / relatif).parent.mkdir(parents=True, exist_ok=True)
                (racine / relatif).write_text("a { color: red }")
            trouves = [p.relative_to(racine).as_posix() for p in fichiers_css(racine)]
            self.assertEqual(trouves, ["static/css/site.css"])

    def test_echoue_si_le_validateur_signale_une_erreur(self):
        with tempfile.TemporaryDirectory() as dossier:
            (Path(dossier) / "page.html").write_text("<p>x</p>")
            with (
                mock.patch("outils.valider_w3c.fichiers_css", return_value=[]),
                mock.patch("outils.valider_w3c.valider", return_value=1) as valider,
                redirect_stdout(io.StringIO()),
                redirect_stderr(io.StringIO()),
            ):
                code = main(["--jar", "vnu.jar", "--html", dossier])
            self.assertEqual(code, 1)
            valider.assert_called_once()

    def test_reussit_sans_page_ni_css(self):
        with (
            tempfile.TemporaryDirectory() as dossier,
            mock.patch("outils.valider_w3c.fichiers_css", return_value=[]),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(main(["--jar", "vnu.jar", "--html", dossier]), 0)
