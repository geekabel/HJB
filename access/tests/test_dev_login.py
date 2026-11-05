"""Login without a passkey, in development only."""

from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.roles import Role
from accounts.tests.helpers import make_user

from .. import dev_login


class DevLoginTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.marie = make_user("marie", Role.ADMIN, first_name="Marie")

    @override_settings(DEBUG=True)
    def test_link_opens_the_staff_area_once(self):
        out = StringIO()
        call_command("dev_login", "marie", stdout=out)
        link = out.getvalue().splitlines()[-1]
        self.assertTrue(link.startswith("http://localhost:8000/dev/connexion/"))
        path = link.removeprefix("http://localhost:8000")
        response = self.client.get(path)
        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("residents:list")).status_code, 200)
        # Sensitive pages too, for 10 minutes (wifi import).
        self.assertEqual(self.client.get(reverse("residents:wifi_import")).status_code, 200)
        self.client.logout()
        self.assertEqual(self.client.get(path).status_code, 404)  # used once

    def test_refused_in_production(self):
        with self.assertRaisesMessage(CommandError, "ne marche qu'en développement"):
            call_command("dev_login", "marie", stdout=StringIO())
        with override_settings(DEBUG=True):
            link = dev_login.make_link(self.marie, "")
        self.assertEqual(self.client.get(link).status_code, 404)  # DEBUG off: 404
        self.assertNotIn("_auth_user_id", self.client.session)

    @override_settings(DEBUG=True)
    def test_bad_or_old_links(self):
        self.assertEqual(self.client.get("/dev/connexion/forged/").status_code, 404)
        self.marie.is_active = False
        self.marie.save()
        link = dev_login.make_link(self.marie, "")
        self.assertEqual(self.client.get(link).status_code, 404)
        with self.assertRaisesMessage(CommandError, "désactivé"):
            call_command("dev_login", "marie", stdout=StringIO())
        with self.assertRaisesMessage(CommandError, "Aucun compte"):
            call_command("dev_login", "nobody", stdout=StringIO())
