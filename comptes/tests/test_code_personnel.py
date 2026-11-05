"""Code d'activation du personnel (carte T14) : action d'administration et commande."""

import io
import re

from django.core.management import CommandError, call_command
from django.test import Client, TestCase
from django.urls import reverse

from activation.tests.test_cle import json_post
from comptes.activation import generer_code
from comptes.models import CodeActivation, User
from comptes.roles import Role
from comptes.tests.outils import connecter, creer_utilisateur
from connexion.tests.authentificateur import Authentificateur
from journal.models import Action, EntreeJournal
from outils.capture_html import enregistrer_page
from sms.fournisseurs import memoire

LISTE_COMPTES = "/admin/comptes/user/"


class ActionAdministrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.marie = creer_utilisateur(
            "marie", Role.ADMIN, is_staff=True, is_superuser=True, first_name="Marie"
        )
        cls.samia = creer_utilisateur(
            "samia", Role.EDUCATEUR, first_name="Samia", telephone="+33612345600"
        )
        cls.awa = creer_utilisateur("awa", telephone="+33612345647")

    def setUp(self):
        connecter(self.client, self.marie)

    def action(self, *comptes):
        return self.client.post(
            LISTE_COMPTES,
            {"action": "generer_code_personnel", "_selected_action": [c.pk for c in comptes]},
            follow=True,
        )

    def test_code_pour_un_membre_du_personnel(self):
        reponse = self.action(self.samia)
        enregistrer_page("admin-code-personnel", reponse)
        self.assertContains(reponse, "Activer votre compte")
        self.assertContains(reponse, reverse("admin:comptes_user_change", args=[self.samia.pk]))
        self.assertEqual(reponse["Cache-Control"].count("no-store"), 1)
        code = CodeActivation.objects.get()
        self.assertTrue(code.pour_personnel)
        self.assertEqual(code.cree_par, self.marie)
        entree = EntreeJournal.objects.get(action=Action.CODE_ACTIVATION_GENERE)
        self.assertTrue(entree.resume().startswith("Code du personnel."))

    def test_pas_pour_un_resident(self):
        reponse = self.action(self.awa)
        self.assertContains(reponse, "son code se génère depuis sa fiche")
        self.assertFalse(CodeActivation.objects.exists())

    def test_un_seul_compte(self):
        reponse = self.action(self.samia, self.marie)
        self.assertContains(reponse, "Choisissez un seul compte.")
        self.assertFalse(CodeActivation.objects.exists())

    def test_reserve_a_l_administration(self):
        # Accès technique, mais sans le rôle Administration : l'action n'existe pas.
        from django.contrib.auth.models import Permission

        technicien = creer_utilisateur("tom", Role.MAINTENANCE, is_staff=True)
        technicien.user_permissions.add(
            *Permission.objects.filter(codename__in=["view_user", "change_user"])
        )
        client = Client()
        connecter(client, technicien)
        self.assertEqual(client.get(LISTE_COMPTES).status_code, 200)
        self.assertNotContains(client.get(LISTE_COMPTES), "generer_code_personnel")
        client.post(
            LISTE_COMPTES,
            {"action": "generer_code_personnel", "_selected_action": [self.samia.pk]},
        )
        self.assertFalse(CodeActivation.objects.exists())


class RevueDroitsTests(TestCase):
    """Cas trouvés par la relecture indépendante de T14."""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth.models import Permission

        modifier = Permission.objects.filter(codename__in=["view_user", "change_user"])
        cls.tom = creer_utilisateur("tom", Role.MAINTENANCE, is_staff=True)
        cls.tom.user_permissions.add(*modifier)
        cls.ali = creer_utilisateur("ali", Role.ADMIN, is_staff=True)
        cls.ali.user_permissions.add(*modifier)
        cls.marie = creer_utilisateur("marie", Role.ADMIN, is_staff=True, is_superuser=True)
        cls.samia = creer_utilisateur("samia", Role.EDUCATEUR, telephone="+33612345600")

    def test_pas_d_auto_promotion(self):
        """Modifier des comptes ne permet pas de se donner des rôles ni des droits."""
        from comptes.tests.test_admin import donnees

        connecter(self.client, self.tom)
        url = reverse("admin:comptes_user_change", args=[self.tom.pk])
        page = self.client.get(url)
        self.assertNotContains(page, 'name="roles"')
        self.assertNotContains(page, 'name="is_superuser"')
        self.assertNotContains(page, 'name="is_staff"')
        self.client.post(
            url, donnees(self.tom, roles=[Role.ADMIN], is_staff="on", is_superuser="on")
        )
        tom = User.objects.get(pk=self.tom.pk)
        self.assertEqual(tom.roles, {Role.MAINTENANCE})
        self.assertFalse(tom.is_superuser)
        self.assertFalse(tom.has_perm("comptes.gerer_roles"))

    def test_seul_un_super_utilisateur_nomme_un_super_utilisateur(self):
        from comptes.tests.test_admin import donnees

        connecter(self.client, self.ali)
        url = reverse("admin:comptes_user_change", args=[self.ali.pk])
        self.assertContains(self.client.get(url), 'name="roles"')
        self.client.post(
            url, donnees(self.ali, roles=[Role.ADMIN], is_staff="on", is_superuser="on")
        )
        self.assertFalse(User.objects.get(pk=self.ali.pk).is_superuser)

    def test_role_ajoute_garde_le_code_du_personnel(self):
        """Ajouter un rôle à un membre du personnel n'annule pas son code du personnel."""
        from comptes.tests.test_admin import donnees

        generer_code(self.samia, pour_personnel=True)
        connecter(self.client, self.marie)
        self.client.post(
            reverse("admin:comptes_user_change", args=[self.samia.pk]),
            donnees(self.samia, telephone="06 12 34 56 00", roles=[Role.EDUCATEUR, Role.ACCUEIL]),
        )
        self.assertEqual(User.objects.get(pk=self.samia.pk).roles, {Role.EDUCATEUR, Role.ACCUEIL})
        self.assertTrue(CodeActivation.objects.valides().filter(pour_personnel=True).exists())

    def test_code_d_un_super_utilisateur(self):
        connecter(self.client, self.ali)
        reponse = self.client.post(
            LISTE_COMPTES,
            {"action": "generer_code_personnel", "_selected_action": [self.marie.pk]},
            follow=True,
        )
        self.assertContains(reponse, "Seul un super-utilisateur")
        self.assertFalse(CodeActivation.objects.exists())


class ActivationDuPersonnelTests(TestCase):
    def setUp(self):
        memoire.boite.clear()
        self.samia = creer_utilisateur(
            "samia", Role.ACCUEIL, first_name="Samia", telephone="+33612345600"
        )

    def test_parcours_complet(self):
        code = generer_code(self.samia, pour_personnel=True)
        self.client.post(reverse("activation:saisie"), {"code": code})
        self.client.post(reverse("activation:telephone"), {"action": "envoyer"})
        sms = re.search(r"\b(\d{6})\b", memoire.boite[-1].texte).group(1)
        self.client.post(reverse("activation:telephone"), {"action": "verifier", "code": sms})
        options = json_post(self.client, reverse("activation:cle_debut")).json()
        reponse = json_post(
            self.client, reverse("activation:cle_fin"), Authentificateur().creer(options)
        )
        self.assertEqual(reponse.status_code, 200)
        # Session du personnel (12 h), vérifiée par la clé : l'espace équipe s'ouvre.
        self.assertEqual(self.client.session.get_expiry_age(), 12 * 3600)
        self.assertRedirects(self.client.get("/"), reverse("residents:liste"))

    def test_code_de_resident_refuse_pour_le_personnel(self):
        self.client.post(reverse("activation:saisie"), {"code": generer_code(self.samia)})
        self.assertRedirects(
            self.client.get(reverse("activation:telephone")), reverse("activation:saisie")
        )

    def test_code_du_personnel_refuse_pour_un_resident(self):
        awa = creer_utilisateur("awa", telephone="+33612345647")
        self.client.post(
            reverse("activation:saisie"), {"code": generer_code(awa, pour_personnel=True)}
        )
        self.assertRedirects(
            self.client.get(reverse("activation:telephone")), reverse("activation:saisie")
        )


class CommandeTests(TestCase):
    def test_premier_administrateur(self):
        User.objects.create_superuser("marie", telephone="+33612345600")
        sortie = io.StringIO()
        call_command("code_activation", "marie", stdout=sortie)
        code = re.search(r"[A-Z0-9]{5}-[A-Z0-9]{5}", sortie.getvalue()).group(0)
        self.assertTrue(CodeActivation.objects.get().pour_personnel)
        self.assertNotIn(code.replace("-", ""), str(list(CodeActivation.objects.values())))

    def test_erreurs(self):
        creer_utilisateur("sans.numero")
        for identifiant, message in (("inconnu", "Aucun compte"), ("sans.numero", "numéro")):
            with (
                self.subTest(identifiant=identifiant),
                self.assertRaisesMessage(CommandError, message),
            ):
                call_command("code_activation", identifiant, stdout=io.StringIO())
