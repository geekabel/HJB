from io import StringIO
from unittest import mock

from django.conf import settings
from django.core.checks import run_checks
from django.core.exceptions import ImproperlyConfigured
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, override_settings

from sms.fournisseurs import memoire
from sms.fournisseurs.base import ErreurConfiguration, ErreurEnvoi, ErreurSms
from sms.service import SEGMENTS_MAX, envoyer_sms

NUMERO = "+33612345678"


class ServiceTests(SimpleTestCase):
    def setUp(self):
        memoire.boite.clear()

    def test_les_tests_n_envoient_jamais_de_vrai_sms(self):
        self.assertEqual(settings.SMS["BACKEND"], "sms.fournisseurs.memoire.FournisseurMemoire")

    def test_envoi(self):
        resultat = envoyer_sms(NUMERO, "  Bonjour  ")
        (sms,) = memoire.boite
        self.assertEqual((sms.numero, sms.texte), (NUMERO, "Bonjour"))
        self.assertEqual(resultat.identifiant, sms.identifiant)

    def test_refus_avant_l_envoi(self):
        cas = [
            ("06 12 34 56 78", "Bonjour", "format international"),
            # Forme E.164 correcte, mais numéro inexistant ou fixe : refusé avant l'envoi.
            ("+999999999", "Bonjour", "portable au format international"),
            ("+33123456789", "Bonjour", "portable au format international"),
            (NUMERO, "   ", "vide"),
            (NUMERO, "a" * (153 * SEGMENTS_MAX + 1), "trop long"),
        ]
        for numero, texte, extrait in cas:
            with self.subTest(extrait), self.assertRaisesMessage(ErreurSms, extrait) as ctx:
                envoyer_sms(numero, texte)
            self.assertFalse(ctx.exception.temporaire)
            self.assertFalse(ctx.exception.incertain)
        self.assertEqual(memoire.boite, [])

    def test_journal_sans_numero_complet_ni_texte(self):
        with self.assertLogs("sms.service", "INFO") as journal:
            envoyer_sms(NUMERO, "Code secret 123456")
        self.assertIn("06 •• •• •• 78", journal.output[0])
        self.assertNotIn("12 34 56", journal.output[0])
        self.assertNotIn("123456", journal.output[0])

    def test_echec_journalise_puis_remonte(self):
        with (
            mock.patch(
                "sms.fournisseurs.memoire.FournisseurMemoire.envoyer",
                side_effect=ErreurEnvoi("refus", temporaire=False),
            ),
            self.assertLogs("sms.service", "WARNING"),
            self.assertRaises(ErreurEnvoi),
        ):
            envoyer_sms(NUMERO, "Bonjour")

    @override_settings(SMS={"BACKEND": "sms.fournisseurs.ovh.FournisseurOvh", "OPTIONS": {}})
    def test_fournisseur_incomplet(self):
        with self.assertRaisesMessage(ErreurConfiguration, "options manquantes"):
            envoyer_sms(NUMERO, "Bonjour")

    @override_settings(SMS={"BACKEND": "sms.inexistant.Fournisseur"})
    def test_fournisseur_inconnu(self):
        with self.assertRaises(ErreurConfiguration):
            envoyer_sms(NUMERO, "Bonjour")


class ReglageTests(SimpleTestCase):
    def test_choix_par_l_environnement(self):
        from config.settings.base import reglage_sms

        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertTrue(reglage_sms("aucun")["BACKEND"].endswith("FournisseurAucun"))
            self.assertTrue(reglage_sms("console")["BACKEND"].endswith("FournisseurConsole"))
        environ = {"DJANGO_SMS_FOURNISSEUR": "smsgate", "SMSGATE_URL": "http://192.0.2.5:8080"}
        with mock.patch.dict("os.environ", environ, clear=True):
            reglage = reglage_sms("aucun")
            self.assertTrue(reglage["BACKEND"].endswith("FournisseurSmsGate"))
            self.assertEqual(reglage["OPTIONS"]["url"], "http://192.0.2.5:8080")
            self.assertEqual(reglage["OPTIONS"]["jeton"], "")
        with (
            mock.patch.dict("os.environ", {"DJANGO_SMS_FOURNISSEUR": "pirate"}, clear=True),
            self.assertRaises(ImproperlyConfigured),
        ):
            reglage_sms("aucun")

    def test_la_production_n_ecrit_pas_les_sms_par_defaut(self):
        # prod.py appelle reglage_sms("aucun") : sans variable, rien ne part ni ne s'affiche.
        from pathlib import Path

        source = (Path(settings.BASE_DIR) / "config/settings/prod.py").read_text()
        self.assertIn('SMS = reglage_sms("aucun")', source)

    def test_lanceur_impose_la_boite_en_memoire_dans_chaque_processus(self):
        from outils.lanceur_tests import SMS_DE_TEST, LanceurTests, imposer_sms_de_test

        self.assertIs(LanceurTests.parallel_test_suite.process_setup, imposer_sms_de_test)
        with override_settings(SMS={"BACKEND": "sms.fournisseurs.ovh.FournisseurOvh"}):
            imposer_sms_de_test()
            self.assertEqual(settings.SMS, SMS_DE_TEST)


class ControlesTests(SimpleTestCase):
    def ids(self, **kwargs):
        return [m.id for m in run_checks(tags=["sms"], **kwargs)]

    def test_configuration_de_test_valide(self):
        self.assertEqual(self.ids(), [])

    @override_settings(
        SMS={"BACKEND": "sms.fournisseurs.smsgate.FournisseurSmsGate", "OPTIONS": {}}
    )
    def test_options_manquantes(self):
        self.assertEqual(self.ids(), ["sms.E002"])

    @override_settings(SMS={"BACKEND": "nulle.part.Fournisseur"})
    def test_fournisseur_introuvable(self):
        self.assertEqual(self.ids(), ["sms.E001"])

    def test_avertissement_au_deploiement(self):
        for classe in ("console.FournisseurConsole", "aucun.FournisseurAucun"):
            with (
                self.subTest(classe),
                override_settings(SMS={"BACKEND": f"sms.fournisseurs.{classe}"}),
            ):
                self.assertEqual(self.ids(include_deployment_checks=True), ["sms.W001"])
                self.assertEqual(self.ids(), [])


class CommandeEssaiTests(SimpleTestCase):
    def setUp(self):
        memoire.boite.clear()

    def test_envoi_d_essai(self):
        sortie = StringIO()
        call_command("envoyer_sms_essai", "06 12 34 56 78", "Fête à l\u2019accueil", stdout=sortie)
        texte = sortie.getvalue()
        self.assertIn("Fournisseur : memoire. Codage : UCS-2", texte)
        self.assertIn("Caractères qui imposent l'UCS-2 : ê \u2019", texte)
        self.assertIn("Envoyé.", texte)
        self.assertEqual(memoire.boite[0].numero, NUMERO)

    def test_numero_illisible(self):
        with self.assertRaisesMessage(CommandError, "Ce numéro n'existe pas"):
            call_command("envoyer_sms_essai", "06 12", "Bonjour", stdout=StringIO())
