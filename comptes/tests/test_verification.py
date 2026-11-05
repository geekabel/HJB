"""Vérification du téléphone par code SMS (carte T12)."""

import re
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from comptes import verification as v
from comptes.models import User, VerificationTelephone
from sms.fournisseurs import memoire
from sms.fournisseurs.base import ErreurEnvoi

from .outils import creer_utilisateur


def dernier_code():
    return re.search(r"\b(\d{6})\b", memoire.boite[-1].texte).group(1)


def vieillir(secondes):
    """Fait comme si les envois dataient de ``secondes`` plus tôt."""
    VerificationTelephone.objects.update(cree_le=timezone.now() - timedelta(seconds=secondes))


class EnvoiTests(TestCase):
    def setUp(self):
        memoire.boite.clear()
        self.awa = creer_utilisateur("awa", telephone="+33612345647")

    def test_envoi(self):
        verification = v.envoyer_code(self.awa)
        (sms,) = memoire.boite
        self.assertEqual(sms.numero, "+33612345647")
        code = dernier_code()
        self.assertIn("expire dans 10 minutes", sms.texte)
        self.assertNotIn(code, verification.empreinte)
        self.assertEqual(verification.telephone, "+33612345647")
        self.assertAlmostEqual(
            verification.expire_le, timezone.now() + v.DUREE, delta=timedelta(seconds=5)
        )

    def test_sans_numero(self):
        with self.assertRaisesMessage(v.ErreurVerification, "Aucun numéro"):
            v.envoyer_code(creer_utilisateur("lina"))

    def test_delai_avant_renvoi(self):
        v.envoyer_code(self.awa)
        with self.assertRaises(v.ErreurVerification) as ctx:
            v.envoyer_code(self.awa)
        self.assertEqual(ctx.exception.code, "trop_tot")
        self.assertTrue(0 < ctx.exception.details["attente"] <= 60)
        vieillir(61)
        v.envoyer_code(self.awa)
        self.assertEqual(len(memoire.boite), 2)

    def test_trois_envois_par_heure(self):
        for _ in range(v.ENVOIS_PAR_HEURE):
            v.envoyer_code(self.awa)
            vieillir(61)
        with self.assertRaises(v.ErreurVerification) as ctx:
            v.envoyer_code(self.awa)
        self.assertEqual(ctx.exception.code, "trop_d_envois")
        vieillir(3601)
        v.envoyer_code(self.awa)

    def test_un_nouveau_code_remplace_l_ancien(self):
        v.envoyer_code(self.awa)
        ancien = dernier_code()
        vieillir(61)
        v.envoyer_code(self.awa)
        nouveau = dernier_code()
        if ancien != nouveau:
            with self.assertRaises(v.ErreurVerification):
                v.verifier_code(self.awa, ancien)
        v.verifier_code(self.awa, nouveau)

    def test_sms_refuse(self):
        with (
            mock.patch(
                "sms.fournisseurs.memoire.FournisseurMemoire.envoyer",
                side_effect=ErreurEnvoi("refus"),
            ),
            self.assertRaises(v.ErreurVerification) as ctx,
        ):
            v.envoyer_code(self.awa)
        self.assertEqual(ctx.exception.code, "sms")
        self.assertFalse(VerificationTelephone.objects.filter(expire_le__gt=timezone.now()))


class VerificationTests(TestCase):
    def setUp(self):
        memoire.boite.clear()
        self.awa = creer_utilisateur("awa", telephone="+33612345647")
        v.envoyer_code(self.awa)
        self.code = dernier_code()

    def faux(self):
        return f"{(int(self.code) + 1) % 10**6:06d}"

    def test_bon_code(self):
        v.verifier_code(self.awa, f" {self.code[:3]} {self.code[3:]} ")
        self.awa.refresh_from_db()
        self.assertIsNotNone(self.awa.telephone_verifie_le)
        with self.assertRaises(v.ErreurVerification):
            v.verifier_code(self.awa, self.code)  # usage unique

    def test_cinq_essais(self):
        for restants in (4, 3, 2, 1):
            with self.assertRaisesMessage(v.ErreurVerification, f"reste {restants} essai"):
                v.verifier_code(self.awa, self.faux())
        with self.assertRaisesMessage(v.ErreurVerification, "dernier essai"):
            v.verifier_code(self.awa, self.faux())
        # Même le bon code ne passe plus.
        with self.assertRaises(v.ErreurVerification) as ctx:
            v.verifier_code(self.awa, self.code)
        self.assertEqual(ctx.exception.code, "trop_essais")

    def test_code_expire(self):
        VerificationTelephone.objects.update(expire_le=timezone.now() - timedelta(seconds=1))
        with self.assertRaisesMessage(v.ErreurVerification, "expiré"):
            v.verifier_code(self.awa, self.code)

    def test_numero_change_entre_temps(self):
        self.awa.telephone = "+33781234588"
        self.awa.save()
        with self.assertRaises(v.ErreurVerification):
            v.verifier_code(self.awa, self.code)

    def test_saisie_invalide_compte_un_essai(self):
        with self.assertRaises(v.ErreurVerification):
            v.verifier_code(self.awa, "abc")
        self.assertEqual(VerificationTelephone.objects.get().tentatives, 1)

    def test_essais_comptes_en_base(self):
        # Deux requêtes simultanées partent du même état : le compteur reste juste.
        VerificationTelephone.objects.update(tentatives=v.ESSAIS_MAX - 1)
        with self.assertRaises(v.ErreurVerification):
            v.verifier_code(self.awa, self.faux())
        with self.assertRaises(v.ErreurVerification) as ctx:
            v.verifier_code(self.awa, self.code)
        self.assertEqual(ctx.exception.code, "trop_essais")
        self.assertEqual(VerificationTelephone.objects.get().tentatives, v.ESSAIS_MAX)


class ChangementDeNumeroTests(TestCase):
    def test_un_nouveau_numero_n_est_pas_verifie(self):
        awa = creer_utilisateur("awa", telephone="+33612345647")
        User.objects.filter(pk=awa.pk).update(telephone_verifie_le=timezone.now())
        awa = User.objects.get(pk=awa.pk)
        awa.first_name = "Awa"
        awa.save()
        self.assertIsNotNone(User.objects.get(pk=awa.pk).telephone_verifie_le)
        awa.telephone = "+33781234588"
        awa.save(update_fields=["telephone"])
        self.assertIsNone(User.objects.get(pk=awa.pk).telephone_verifie_le)
