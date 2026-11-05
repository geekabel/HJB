"""Activation, étape 2 : vérification du téléphone (carte T12)."""

import re

from django.test import TestCase
from django.urls import reverse

from activation import parcours
from comptes.activation import generer_code
from comptes.models import VerificationTelephone
from comptes.tests.outils import creer_utilisateur
from outils.capture_html import enregistrer_page
from sms.fournisseurs import memoire


class EtapeTelephoneTests(TestCase):
    def setUp(self):
        memoire.boite.clear()
        self.awa = creer_utilisateur("awa", first_name="Awa", telephone="+33612345647")
        self.url = reverse("activation:telephone")
        self.client.post(reverse("activation:saisie"), {"code": generer_code(self.awa)})

    def envoyer(self):
        return self.client.post(self.url, {"action": "envoyer"}, follow=True)

    def code_recu(self):
        return re.search(r"\b(\d{6})\b", memoire.boite[-1].texte).group(1)

    def test_avant_l_envoi(self):
        reponse = self.client.get(self.url)
        enregistrer_page("activation-telephone", reponse)
        self.assertContains(reponse, 'aria-current="step">2. Téléphone')
        self.assertContains(reponse, "06 •• •• •• 47")
        self.assertContains(reponse, "Recevoir le code par SMS")
        self.assertEqual(memoire.boite, [])  # rien n'est envoyé sur un simple affichage

    def test_parcours_complet(self):
        reponse = self.envoyer()
        enregistrer_page("activation-telephone-code", reponse)
        self.assertContains(reponse, "Code envoyé.")
        self.assertContains(reponse, 'autocomplete="one-time-code"')
        self.assertContains(reponse, "Possible dans")
        reponse = self.client.post(
            self.url, {"action": "verifier", "code": self.code_recu()}, follow=True
        )
        self.assertRedirects(reponse, reverse("activation:cle"))
        enregistrer_page("activation-cle", reponse)
        self.assertContains(reponse, "Votre téléphone est vérifié.")
        self.assertContains(reponse, 'aria-current="step">3. Clé d\'accès')
        self.awa.refresh_from_db()
        self.assertIsNotNone(self.awa.telephone_verifie_le)
        # Revenir à l'étape 2 mène à l'étape 3.
        self.assertRedirects(self.client.get(self.url), reverse("activation:cle"))

    def test_mauvais_code(self):
        self.envoyer()
        reponse = self.client.post(self.url, {"action": "verifier", "code": "000000"})
        if self.code_recu() == "000000":
            return
        enregistrer_page("activation-telephone-erreur", reponse)
        self.assertContains(reponse, "Code incorrect. Il vous reste 4 essais.")
        self.assertContains(reponse, 'aria-invalid="true"')

    def test_renvoi_trop_tot(self):
        self.envoyer()
        reponse = self.envoyer()
        self.assertContains(reponse, "Patientez")
        self.assertEqual(len(memoire.boite), 1)

    def test_sans_numero(self):
        lina = creer_utilisateur("lina", first_name="Lina")
        self.client.post(reverse("activation:saisie"), {"code": generer_code(lina)})
        reponse = self.client.get(self.url)
        self.assertContains(reponse, "Aucun numéro n'est enregistré pour vous.")
        self.assertNotContains(reponse, "Recevoir le code")

    def test_pas_mon_numero(self):
        reponse = self.client.get(reverse("activation:mauvais_numero"))
        enregistrer_page("activation-mauvais-numero", reponse)
        self.assertContains(reponse, "Passez à l'accueil avec une pièce d'identité.")
        self.assertNotIn(parcours.CLE, self.client.session)

    def test_etape_3_sans_verification(self):
        self.assertRedirects(self.client.get(reverse("activation:cle")), self.url)

    def test_les_codes_ne_sont_pas_en_clair(self):
        self.envoyer()
        code = self.code_recu()
        self.assertNotIn(code, VerificationTelephone.objects.get().empreinte)
