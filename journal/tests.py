from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase
from django.urls import reverse

from comptes.models import User
from comptes.roles import Role
from comptes.tests.outils import connecter, creer_utilisateur
from outils.capture_html import enregistrer_page

from .models import Action, EntreeJournal, EntreeJournalNonModifiable
from .service import journaliser


class JournaliserTests(TestCase):
    def setUp(self):
        self.admin = creer_utilisateur("marie", Role.ADMIN)
        self.cible = creer_utilisateur("awa")

    def requete(self, utilisateur, ip="192.0.2.10"):
        requete = RequestFactory().get("/", REMOTE_ADDR=ip)
        requete.user = utilisateur
        return requete

    def test_acteur_ip_cible_et_details(self):
        entree = journaliser(
            Action.ROLES_MODIFIES,
            cible=self.cible,
            details={"avant": [], "apres": ["ACCUEIL"]},
            requete=self.requete(self.admin),
        )
        entree.refresh_from_db()
        self.assertEqual(entree.acteur, self.admin)
        self.assertEqual(entree.acteur_libelle, "marie")
        self.assertEqual(entree.adresse_ip, "192.0.2.10")
        self.assertEqual(entree.cible, self.cible)
        self.assertEqual(entree.cible_libelle, "awa")
        self.assertEqual(entree.resume(), "Avant : aucun (résident). Après : Accueil.")

    def test_sans_requete_ni_acteur(self):
        entree = journaliser(Action.DEPART_RESIDENT, cible=self.cible)
        self.assertIsNone(entree.acteur)
        self.assertIsNone(entree.adresse_ip)

    def test_anonyme(self):
        entree = journaliser(Action.DEPART_RESIDENT, requete=self.requete(AnonymousUser()))
        self.assertIsNone(entree.acteur)

    def test_ne_se_modifie_pas(self):
        entree = journaliser(Action.DEPART_RESIDENT, cible=self.cible)
        entree.cible_libelle = "autre"
        with self.assertRaises(EntreeJournalNonModifiable):
            entree.save()
        with self.assertRaises(EntreeJournalNonModifiable):
            entree.delete()

    def test_reste_lisible_apres_suppression_des_comptes(self):
        journaliser(Action.ROLES_MODIFIES, cible=self.cible, requete=self.requete(self.admin))
        self.cible.delete()
        self.admin.delete()
        entree = EntreeJournal.objects.get()
        self.assertIsNone(entree.acteur)
        self.assertIsNone(entree.cible)
        self.assertEqual((entree.acteur_libelle, entree.cible_libelle), ("marie", "awa"))


class ChangementDeRolesJournaliseTests(TestCase):
    def test_l_admin_django_journalise_le_changement(self):
        admin = User.objects.create_superuser(username="admin", password="mot-de-passe-test")
        marc = creer_utilisateur("marc", Role.MAINTENANCE)
        connecter(self.client, admin)
        donnees = {
            "username": "marc",
            "telephone": "",
            "is_active": "on",
            "date_joined_0": "2026-11-05",
            "date_joined_1": "09:00:00",
        }
        url = reverse("admin:comptes_user_change", args=[marc.pk])
        self.client.post(url, donnees | {"roles": [Role.ACCUEIL, Role.MAINTENANCE]})
        entree = EntreeJournal.objects.get()
        self.assertEqual(entree.action, Action.ROLES_MODIFIES)
        self.assertEqual(entree.acteur, admin)
        self.assertEqual(
            entree.details, {"avant": ["MAINTENANCE"], "apres": ["ACCUEIL", "MAINTENANCE"]}
        )
        # Enregistrer sans changer les rôles n'ajoute rien.
        self.client.post(url, donnees | {"roles": [Role.ACCUEIL, Role.MAINTENANCE]})
        self.assertEqual(EntreeJournal.objects.count(), 1)


class PageJournalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = creer_utilisateur("marie", Role.ADMIN)
        cls.accueil = creer_utilisateur("ines", Role.ACCUEIL)
        cible = creer_utilisateur("awa")
        journaliser(
            Action.ROLES_MODIFIES,
            acteur=cls.admin,
            cible=cible,
            details={"avant": [], "apres": ["ACCUEIL"]},
        )
        journaliser(Action.DEPART_RESIDENT, acteur=cls.admin, cible=cible)

    def test_reserve_a_l_administration(self):
        url = reverse("journal:liste")
        self.assertEqual(self.client.get(url).status_code, 302)
        connecter(self.client, self.accueil)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_liste_et_lien_dans_le_menu(self):
        connecter(self.client, self.admin)
        reponse = self.client.get(reverse("journal:liste"))
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Avant : aucun (résident). Après : Accueil.")
        self.assertContains(reponse, "Départ d&#x27;un résident")
        # Texte écrit en dur dans le gabarit : Django ne l'échappe pas.
        self.assertContains(reponse, 'aria-current="page">Journal d\'audit</a>')
        # Sur mobile, le tableau défile : la zone doit être atteignable au clavier.
        self.assertContains(reponse, 'role="region" aria-labelledby="legende-journal" tabindex="0"')
        enregistrer_page("journal-audit", reponse)

    def test_filtre_par_action(self):
        connecter(self.client, self.admin)
        reponse = self.client.get(reverse("journal:liste"), {"action": Action.DEPART_RESIDENT})
        self.assertEqual(len(reponse.context["page_obj"]), 1)
        # Une valeur inconnue est ignorée.
        reponse = self.client.get(reverse("journal:liste"), {"action": "<script>"})
        self.assertEqual(len(reponse.context["page_obj"]), 2)

    def test_aucune_entree_pour_cette_action(self):
        connecter(self.client, self.admin)
        reponse = self.client.get(reverse("journal:liste"), {"action": Action.CODE_WIFI_AFFICHE})
        self.assertContains(reponse, "Aucune entrée pour cette action")
        enregistrer_page("journal-audit-vide", reponse)

    def test_lien_absent_pour_les_autres_roles(self):
        connecter(self.client, self.accueil)
        reponse = self.client.get(reverse("interface:guide"))
        self.assertNotContains(reponse, reverse("journal:liste"))
