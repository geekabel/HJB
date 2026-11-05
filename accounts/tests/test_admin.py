from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from accounts.roles import Role

from .helpers import log_in_verified, make_user


def form_data(user, **fields):
    """Minimal data for the admin change form."""
    base = {
        "username": user.username,
        "first_name": "",
        "last_name": "",
        "email": "",
        "phone": "",
        "is_active": "on",
        "date_joined_0": "2026-11-05",
        "date_joined_1": "09:00:00",
    }
    base.update(fields)
    return base


class UserAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(username="admin", password="test-password")

    def setUp(self):
        log_in_verified(self.client, self.admin)

    def test_add_change_and_list_pages(self):
        resident = make_user("awa")
        for url in (
            reverse("admin:accounts_user_add"),
            reverse("admin:accounts_user_change", args=[resident.pk]),
            reverse("admin:accounts_user_changelist"),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_check_several_roles(self):
        marc = make_user("marc", Role.MAINTENANCE)
        response = self.client.post(
            reverse("admin:accounts_user_change", args=[marc.pk]),
            form_data(marc, phone="07 81 22 33 44", roles=[Role.FRONT_DESK, Role.MAINTENANCE]),
        )
        self.assertEqual(response.status_code, 302)
        marc = User.objects.get(pk=marc.pk)
        self.assertEqual(marc.roles, {Role.FRONT_DESK, Role.MAINTENANCE})
        self.assertEqual(marc.phone, "+33781223344")
        self.assertTrue(marc.has_perm("accounts.manage_residents"))

    def test_changing_roles_closes_sessions_and_cancels_the_code(self):
        """T13 review: a resident promoted to the front desk logs in again (rights, session
        length)."""
        from django.test import Client

        from accounts.activation_codes import issue_code
        from accounts.models import ActivationCode

        awa = make_user("awa")
        issue_code(awa)
        awa_session = Client()
        awa_session.force_login(awa)
        self.client.post(
            reverse("admin:accounts_user_change", args=[awa.pk]),
            form_data(awa, roles=[Role.FRONT_DESK]),
        )
        self.assertEqual(awa_session.get("/").status_code, 302)  # sent back to the login page
        self.assertFalse(ActivationCode.objects.valid().exists())
        # The session of the administrator who makes the change stays open.
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 200)

    def test_uncheck_all_roles(self):
        ines = make_user("ines", Role.FRONT_DESK)
        self.client.post(reverse("admin:accounts_user_change", args=[ines.pk]), form_data(ines))
        self.assertEqual(User.objects.get(pk=ines.pk).roles, set())

    def test_create_with_roles(self):
        response = self.client.post(
            reverse("admin:accounts_user_add"),
            {
                "username": "samia",
                "first_name": "Samia",
                "last_name": "B.",
                "phone": "06 12 34 56 78",
                "roles": [Role.EDUCATOR],
            },
        )
        self.assertEqual(response.status_code, 302)
        samia = User.objects.get(username="samia")
        self.assertEqual(samia.roles, {Role.EDUCATOR})
        self.assertEqual(samia.phone, "+33612345678")
        # Card T14: no password, the person will activate their account with a code.
        self.assertFalse(samia.has_usable_password())

    def test_refused_number_with_clear_message(self):
        marc = make_user("marc")
        response = self.client.post(
            reverse("admin:accounts_user_change", args=[marc.pk]),
            form_data(marc, phone="06 12"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ce numéro n&#x27;existe pas")
