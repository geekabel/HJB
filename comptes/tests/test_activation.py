"""Codes d'activation (carte T11)."""

from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from comptes.activation import (
    ECHECS_MAX,
    ErreurActivation,
    empreinte,
    envoyer_code_par_sms,
    etat_activation,
    formater,
    generer_code,
    normaliser,
    utiliser_code,
)
from comptes.models import CodeActivation, EchecActivation
from comptes.roles import Role
from journal.models import Action, EntreeJournal
from sms.fournisseurs import memoire
from sms.fournisseurs.base import ErreurEnvoi

from .outils import creer_utilisateur

IP = "192.0.2.10"


class CodeTests(TestCase):
    def setUp(self):
        self.accueil = creer_utilisateur("nadia", Role.ACCUEIL)
        self.awa = creer_utilisateur("awa", first_name="Awa", telephone="+33612345647")

    def test_format_et_stockage(self):
        code = generer_code(self.awa, par=self.accueil)
        self.assertRegex(code, r"^[A-HJKMNP-TV-Z2-9]{5}-[A-HJKMNP-TV-Z2-9]{5}$")
        enregistre = CodeActivation.objects.get()
        # Seule l'empreinte est en base, jamais le code.
        self.assertEqual(enregistre.empreinte, empreinte(code))
        self.assertNotIn(normaliser(code), enregistre.empreinte)
        self.assertEqual(enregistre.cree_par, self.accueil)
        self.assertAlmostEqual(
            enregistre.expire_le, timezone.now() + timedelta(hours=72), delta=timedelta(minutes=1)
        )
        entree = EntreeJournal.objects.get(action=Action.CODE_ACTIVATION_GENERE)
        self.assertEqual((entree.acteur, entree.cible), (self.accueil, self.awa))
        self.assertTrue(entree.resume().startswith("Valable jusqu'au "))

    def test_saisie_souple(self):
        self.assertEqual(normaliser(" abcde fghjk "), "ABCDEFGHJK")
        self.assertEqual(normaliser("ABCDE-FGHJK"), "ABCDEFGHJK")
        self.assertEqual(formater("ABCDEFGHJK"), "ABCDE-FGHJK")
        code = generer_code(self.awa)
        self.assertEqual(utiliser_code(code.lower().replace("-", " "), IP).utilisateur, self.awa)

    def test_usage_unique(self):
        code = generer_code(self.awa)
        trouve = utiliser_code(code, IP)
        self.assertIsNotNone(CodeActivation.objects.get(pk=trouve.pk).utilise_le)
        with self.assertRaisesMessage(ErreurActivation, "ne marche pas"):
            utiliser_code(code, IP)

    def test_un_nouveau_code_annule_l_ancien(self):
        ancien = generer_code(self.awa)
        nouveau = generer_code(self.awa)
        with self.assertRaises(ErreurActivation):
            utiliser_code(ancien, IP)
        self.assertEqual(utiliser_code(nouveau, IP).utilisateur, self.awa)

    def test_code_expire(self):
        code = generer_code(self.awa)
        CodeActivation.objects.update(expire_le=timezone.now() - timedelta(seconds=1))
        with self.assertRaises(ErreurActivation):
            utiliser_code(code, IP)

    def test_compte_desactive(self):
        code = generer_code(self.awa)
        self.awa.is_active = False
        self.awa.save()
        with self.assertRaises(ErreurActivation):
            utiliser_code(code, IP)

    def test_course_entre_deux_appareils(self):
        code = generer_code(self.awa)
        # L'autre appareil a utilisé le code entre la recherche et la mise à jour.
        original = CodeActivation.objects.valides

        def valides_puis_utilise(*args, **kwargs):
            resultat = list(original(*args, **kwargs))
            CodeActivation.objects.update(utilise_le=timezone.now())
            return CodeActivation.objects.filter(pk__in=[c.pk for c in resultat])

        with (
            mock.patch.object(CodeActivation.objects, "valides", valides_puis_utilise),
            self.assertRaises(ErreurActivation),
        ):
            utiliser_code(code, IP)

    def test_limite_d_essais_par_adresse(self):
        code = generer_code(self.awa)
        for _ in range(ECHECS_MAX):
            with self.assertRaises(ErreurActivation):
                utiliser_code("AAAAA-AAAAA", IP)
        with self.assertRaises(ErreurActivation) as ctx:
            utiliser_code(code, IP)  # même le bon code est refusé pendant une heure
        self.assertEqual(ctx.exception.code, "trop_essais")
        # Une autre adresse n'est pas bloquée.
        self.assertEqual(utiliser_code(code, "192.0.2.99").utilisateur, self.awa)
        # Après une heure, l'adresse est débloquée.
        EchecActivation.objects.update(cree_le=timezone.now() - timedelta(hours=2))
        self.assertEqual(utiliser_code(generer_code(self.awa), IP).utilisateur, self.awa)

    def test_menage_des_vieux_echecs(self):
        EchecActivation.objects.create(adresse_ip=IP)
        EchecActivation.objects.update(cree_le=timezone.now() - timedelta(days=2))
        with self.assertRaises(ErreurActivation):
            utiliser_code("AAAAA-AAAAA", IP)
        self.assertEqual(EchecActivation.objects.count(), 1)

    def test_empreinte_liee_a_la_cle_secrete(self):
        with self.settings(SECRET_KEY="cle-a" * 10):
            a = empreinte("ABCDEFGHJK")
        with self.settings(SECRET_KEY="cle-b" * 10):
            b = empreinte("ABCDEFGHJK")
        self.assertNotEqual(a, b)

    def test_etat(self):
        self.assertEqual(etat_activation(self.awa), (None, None))
        code = generer_code(self.awa)
        self.assertEqual(etat_activation(self.awa)[1], "actif")
        utiliser_code(code, IP)
        self.assertEqual(etat_activation(self.awa)[1], "utilise")
        generer_code(self.awa)
        CodeActivation.objects.filter(utilise_le__isnull=True).update(
            expire_le=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(etat_activation(self.awa)[1], "expire")


class CodeParSmsTests(TestCase):
    ADRESSE = "https://hjb.exemple/activer/"

    def setUp(self):
        memoire.boite.clear()
        self.awa = creer_utilisateur("awa", telephone="+33612345647")

    def test_envoi(self):
        self.assertTrue(envoyer_code_par_sms(self.awa, self.ADRESSE))
        (sms,) = memoire.boite
        self.assertEqual(sms.numero, "+33612345647")
        self.assertRegex(sms.texte, r"https://hjb\.exemple/activer/#[A-Z2-9]{5}-[A-Z2-9]{5}")
        self.assertIn("valable 72 h", sms.texte)
        self.assertEqual(etat_activation(self.awa)[1], "actif")

    def test_sans_numero(self):
        self.assertFalse(envoyer_code_par_sms(creer_utilisateur("lina"), self.ADRESSE))
        self.assertEqual(memoire.boite, [])
        self.assertFalse(CodeActivation.objects.exists())

    def test_echec_annule_le_code(self):
        with mock.patch(
            "sms.fournisseurs.memoire.FournisseurMemoire.envoyer",
            side_effect=ErreurEnvoi("refus", temporaire=False),
        ):
            self.assertFalse(envoyer_code_par_sms(self.awa, self.ADRESSE))
        self.assertEqual(etat_activation(self.awa)[1], "expire")

    def test_envoi_incertain_garde_le_code(self):
        with mock.patch(
            "sms.fournisseurs.memoire.FournisseurMemoire.envoyer",
            side_effect=ErreurEnvoi("délai", incertain=True),
        ):
            self.assertTrue(envoyer_code_par_sms(self.awa, self.ADRESSE))
        self.assertEqual(etat_activation(self.awa)[1], "actif")
