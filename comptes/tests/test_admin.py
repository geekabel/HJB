from django.test import TestCase
from django.urls import reverse

from comptes.models import User
from comptes.roles import Role

from .outils import connecter, creer_utilisateur


def donnees(utilisateur, **champs):
    """Données minimales du formulaire de modification de l'administration."""
    base = {
        "username": utilisateur.username,
        "first_name": "",
        "last_name": "",
        "email": "",
        "telephone": "",
        "is_active": "on",
        "date_joined_0": "2026-11-05",
        "date_joined_1": "09:00:00",
    }
    base.update(champs)
    return base


class AdministrationUtilisateursTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(username="admin", password="mot-de-passe-test")

    def setUp(self):
        connecter(self.client, self.admin)

    def test_pages_de_creation_de_modification_et_liste(self):
        resident = creer_utilisateur("awa")
        for url in (
            reverse("admin:comptes_user_add"),
            reverse("admin:comptes_user_change", args=[resident.pk]),
            reverse("admin:comptes_user_changelist"),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_cocher_plusieurs_roles(self):
        marc = creer_utilisateur("marc", Role.MAINTENANCE)
        reponse = self.client.post(
            reverse("admin:comptes_user_change", args=[marc.pk]),
            donnees(marc, telephone="07 81 22 33 44", roles=[Role.ACCUEIL, Role.MAINTENANCE]),
        )
        self.assertEqual(reponse.status_code, 302)
        marc = User.objects.get(pk=marc.pk)
        self.assertEqual(marc.roles, {Role.ACCUEIL, Role.MAINTENANCE})
        self.assertEqual(marc.telephone, "+33781223344")
        self.assertTrue(marc.has_perm("comptes.gerer_residents"))

    def test_changer_les_roles_ferme_les_sessions_et_annule_le_code(self):
        """Revue T13 : un résident promu à l'accueil se reconnecte (droits, durée de session)."""
        from django.test import Client

        from comptes.activation import generer_code
        from comptes.models import CodeActivation

        awa = creer_utilisateur("awa")
        generer_code(awa)
        session_awa = Client()
        session_awa.force_login(awa)
        self.client.post(
            reverse("admin:comptes_user_change", args=[awa.pk]),
            donnees(awa, roles=[Role.ACCUEIL]),
        )
        self.assertEqual(session_awa.get("/").status_code, 302)  # renvoyée vers la connexion
        self.assertFalse(CodeActivation.objects.valides().exists())
        # La session de l'administrateur qui fait la modification reste ouverte.
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 200)

    def test_decocher_tous_les_roles(self):
        ines = creer_utilisateur("ines", Role.ACCUEIL)
        self.client.post(reverse("admin:comptes_user_change", args=[ines.pk]), donnees(ines))
        self.assertEqual(User.objects.get(pk=ines.pk).roles, set())

    def test_creation_avec_roles(self):
        reponse = self.client.post(
            reverse("admin:comptes_user_add"),
            {
                "username": "samia",
                "first_name": "Samia",
                "last_name": "B.",
                "telephone": "06 12 34 56 78",
                "roles": [Role.EDUCATEUR],
            },
        )
        self.assertEqual(reponse.status_code, 302)
        samia = User.objects.get(username="samia")
        self.assertEqual(samia.roles, {Role.EDUCATEUR})
        self.assertEqual(samia.telephone, "+33612345678")
        # Carte T14 : aucun mot de passe, la personne activera son compte par code.
        self.assertFalse(samia.has_usable_password())

    def test_numero_refuse_avec_message_clair(self):
        marc = creer_utilisateur("marc")
        reponse = self.client.post(
            reverse("admin:comptes_user_change", args=[marc.pk]), donnees(marc, telephone="06 12")
        )
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Ce numéro n&#x27;existe pas")
