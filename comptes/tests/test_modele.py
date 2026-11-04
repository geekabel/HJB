import os
import subprocess
import sys

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from comptes.models import User


class ModeleUtilisateurTests(TestCase):
    def test_le_modele_actif_est_le_modele_du_projet(self):
        self.assertEqual(settings.AUTH_USER_MODEL, "comptes.User")
        self.assertIs(get_user_model(), User)

    def test_creer_un_utilisateur_hache_le_mot_de_passe(self):
        utilisateur = User.objects.create_user(username="awa", password="un-mot-de-passe-solide")
        self.assertNotEqual(utilisateur.password, "un-mot-de-passe-solide")
        self.assertTrue(utilisateur.check_password("un-mot-de-passe-solide"))

    def test_page_de_connexion_admin_repond(self):
        reponse = self.client.get("/admin/login/")
        self.assertEqual(reponse.status_code, 200)


class ReglagesCommunsTests(SimpleTestCase):
    def test_langue_et_fuseau(self):
        self.assertEqual(settings.LANGUAGE_CODE, "fr-fr")
        self.assertEqual(settings.TIME_ZONE, "Europe/Paris")
        self.assertTrue(settings.USE_TZ)


class ReglagesProductionTests(SimpleTestCase):
    """Les réglages de production se chargent dans un processus séparé,
    pour ne pas toucher aux réglages des tests en cours."""

    def _importer_prod(self, **variables):
        environnement = {
            cle: valeur
            for cle, valeur in os.environ.items()
            if not cle.startswith(("DJANGO_", "POSTGRES_"))
        }
        environnement.update(variables)
        return subprocess.run(
            [
                sys.executable,
                "-c",
                "import config.settings.prod as p; print(p.DEBUG, p.ALLOWED_HOSTS)",
            ],
            cwd=settings.BASE_DIR,
            env=environnement,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_refuse_de_demarrer_sans_cle_secrete(self):
        resultat = self._importer_prod()
        self.assertNotEqual(resultat.returncode, 0)
        self.assertIn("DJANGO_SECRET_KEY", resultat.stderr)

    def test_lit_la_cle_et_les_hotes_depuis_l_environnement(self):
        resultat = self._importer_prod(
            DJANGO_SECRET_KEY="cle-de-test",
            DJANGO_ALLOWED_HOSTS="residence.example, www.residence.example",
        )
        self.assertEqual(resultat.returncode, 0, resultat.stderr)
        self.assertEqual(
            resultat.stdout.strip(),
            "False ['residence.example', 'www.residence.example']",
        )
