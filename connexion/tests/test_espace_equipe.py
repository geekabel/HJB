"""Espace équipe et administration : personnel avec clé d'accès, sans mot de passe (carte T14)."""

import json

from django.contrib.auth import SESSION_KEY, authenticate
from django.test import TestCase, override_settings
from django.urls import reverse

from comptes.models import User
from comptes.roles import Role
from comptes.tests.outils import connecter, creer_utilisateur

from .authentificateur import Authentificateur

LISTE = "/equipe/residents/"


class EspaceEquipeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.accueil = creer_utilisateur("nadia", Role.ACCUEIL)
        cls.awa = creer_utilisateur("awa")
        cls.admin = creer_utilisateur("marie", Role.ADMIN, is_staff=True, is_superuser=True)

    def test_anonyme(self):
        self.assertRedirects(
            self.client.get(LISTE), f"/connexion/?next={LISTE}", fetch_redirect_response=False
        )

    def test_resident_refuse(self):
        connecter(self.client, self.awa)
        for chemin in (LISTE, "/equipe/journal/", "/guide/", "/equipe/nouvelle-page/"):
            with self.subTest(chemin=chemin):
                self.assertEqual(self.client.get(chemin).status_code, 403)

    def test_personnel_sans_cle_verifiee(self):
        # Session ouverte sans clé d'accès : il faut la confirmer avec une clé.
        self.client.force_login(self.accueil)
        self.assertRedirects(
            self.client.get(LISTE),
            f"{reverse('connexion:confirmer')}?next=%2Fequipe%2Fresidents%2F",
            fetch_redirect_response=False,
        )

    def test_personnel_verifie(self):
        connecter(self.client, self.accueil)
        self.assertEqual(self.client.get(LISTE).status_code, 200)

    def test_connexion_par_cle_puis_espace_equipe(self):
        telephone = Authentificateur()
        telephone.enregistrer(self.accueil)
        options = self.client.post(reverse("connexion:verification_debut")).json()
        reponse = self.client.post(
            f"{reverse('connexion:verification_fin')}?next={LISTE}",
            data=json.dumps(telephone.verifier(options)),
            content_type="application/json",
        )
        self.assertEqual(reponse.json()["redirect_url"], LISTE)
        self.assertEqual(self.client.get(LISTE).status_code, 200)


class AdministrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.accueil = creer_utilisateur("nadia", Role.ACCUEIL)
        cls.admin = User.objects.create_superuser("marie", password="mot-de-passe-test")

    def test_personnel_sans_acces_technique(self):
        # L'accueil n'a pas is_staff : l'administration Django lui est fermée.
        connecter(self.client, self.accueil)
        self.assertEqual(self.client.get("/admin/").status_code, 403)

    def test_administrateur_verifie(self):
        connecter(self.client, self.admin)
        self.assertEqual(self.client.get("/admin/").status_code, 200)
        # La page de connexion de l'administration renvoie vers la suite, sans formulaire.
        reponse = self.client.get("/admin/login/?next=/admin/comptes/user/")
        self.assertRedirects(reponse, "/admin/comptes/user/", fetch_redirect_response=False)
        reponse = self.client.get("/admin/login/?next=https://pirate.example/")
        self.assertRedirects(reponse, "/admin/", fetch_redirect_response=False)

    def test_administrateur_non_verifie(self):
        self.client.force_login(self.admin)
        reponse = self.client.get("/admin/")
        self.assertTrue(reponse["Location"].startswith(reverse("connexion:confirmer")))

    def test_aucun_mot_de_passe_accepte(self):
        self.assertIsNone(authenticate(username="marie", password="mot-de-passe-test"))
        self.client.post("/admin/login/", {"username": "marie", "password": "mot-de-passe-test"})
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_les_permissions_des_roles_restent(self):
        self.assertTrue(self.accueil.has_perm("comptes.gerer_residents"))
        self.assertFalse(creer_utilisateur("awa").has_perm("comptes.gerer_residents"))

    @override_settings(ADMIN_URL="gestion-7f3k/")
    def test_controle_de_l_adresse(self):
        from connexion.checks import adresse_administration

        self.assertEqual(adresse_administration(None), [])
        with self.settings(ADMIN_URL="admin/"):
            self.assertEqual(adresse_administration(None)[0].id, "connexion.W001")
