"""Activation, étape 1 : saisie du code (carte T11)."""

import time

from django.test import TestCase
from django.urls import reverse

from activation import parcours
from comptes.activation import generer_code
from comptes.models import CodeActivation
from comptes.tests.outils import creer_utilisateur
from outils.capture_html import enregistrer_page


class SaisieTests(TestCase):
    def setUp(self):
        self.awa = creer_utilisateur("awa", first_name="Awa", telephone="+33612345647")
        self.url = reverse("activation:saisie")

    def test_page(self):
        reponse = self.client.get(self.url)
        enregistrer_page("activation-saisie", reponse)
        self.assertContains(reponse, "Activer mon compte")
        self.assertContains(reponse, 'aria-current="step">1. Code reçu')
        self.assertContains(reponse, "code-depuis-lien.js")
        self.assertNotContains(reponse, "nav-resident")
        self.assertIn("no-cache", reponse["Cache-Control"])

    def test_bon_code(self):
        code = generer_code(self.awa)
        self.client.get(self.url)
        cle_avant = self.client.session.session_key
        reponse = self.client.post(self.url, {"code": code})
        self.assertRedirects(
            reponse, reverse("activation:telephone"), fetch_redirect_response=False
        )
        self.assertNotEqual(self.client.session.session_key, cle_avant)
        self.assertEqual(self.client.session[parcours.CLE]["utilisateur"], self.awa.pk)
        self.assertIsNotNone(CodeActivation.objects.get().utilise_le)
        # Pas de connexion à ce stade : il faudra la clé d'accès (T13).
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_mauvais_code(self):
        reponse = self.client.post(self.url, {"code": "AAAAA-AAAAA"})
        enregistrer_page("activation-saisie-erreur", reponse)
        self.assertContains(reponse, "Ce code ne marche pas.")
        self.assertContains(reponse, 'aria-invalid="true"')
        self.assertNotIn(parcours.CLE, self.client.session)

    def test_suite_sans_code(self):
        reponse = self.client.get(reverse("activation:telephone"), follow=True)
        self.assertRedirects(reponse, self.url)
        self.assertContains(reponse, "saisissez le code remis par l&#x27;accueil")

    def test_parcours_limite_a_une_heure(self):
        self.client.post(self.url, {"code": generer_code(self.awa)})
        session = self.client.session
        session[parcours.CLE]["debut"] = time.time() - parcours.DUREE - 1
        session.save()
        reponse = self.client.get(reverse("activation:telephone"))
        self.assertRedirects(reponse, self.url)
