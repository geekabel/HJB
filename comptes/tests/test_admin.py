from django.test import TestCase
from django.urls import reverse

from comptes.models import User
from comptes.roles import Role


class AdministrationUtilisateursTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(username="admin", password="mot-de-passe-test")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_pages_de_creation_et_de_modification(self):
        resident = User.objects.create_user(username="awa")
        for url in (
            reverse("admin:comptes_user_add"),
            reverse("admin:comptes_user_change", args=[resident.pk]),
            reverse("admin:comptes_user_changelist"),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_changer_le_role_dans_l_admin_change_le_groupe(self):
        marc = User.objects.create_user(username="marc", role=Role.MAINTENANCE)
        reponse = self.client.post(
            reverse("admin:comptes_user_change", args=[marc.pk]),
            {
                "username": "marc",
                "first_name": "",
                "last_name": "",
                "email": "",
                "telephone": "07 81 22 33 44",
                "role": Role.ACCUEIL,
                "is_active": "on",
                "date_joined_0": "2026-11-05",
                "date_joined_1": "09:00:00",
            },
        )
        self.assertEqual(reponse.status_code, 302, getattr(reponse, "context", None))
        marc.refresh_from_db()
        self.assertEqual(marc.role, Role.ACCUEIL)
        self.assertEqual(marc.telephone, "+33781223344")
        self.assertEqual(list(marc.groups.values_list("name", flat=True)), ["Accueil"])

    def test_numero_refuse_avec_message_clair(self):
        marc = User.objects.create_user(username="marc")
        reponse = self.client.post(
            reverse("admin:comptes_user_change", args=[marc.pk]),
            {
                "username": "marc",
                "telephone": "06 12",
                "role": Role.RESIDENT,
                "is_active": "on",
                "date_joined_0": "2026-11-05",
                "date_joined_1": "09:00:00",
            },
        )
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Ce numéro n&#x27;existe pas")
