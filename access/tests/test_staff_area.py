"""Staff area and admin site: staff with a passkey, no password (card T14)."""

import json

from django.contrib.auth import authenticate
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user

from .authenticator import SoftwareAuthenticator

LIST_URL = "/equipe/residents/"


class StaffAreaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.front_desk = make_user("nadia", Role.FRONT_DESK)
        cls.awa = make_user("awa")
        cls.admin = make_user("marie", Role.ADMIN, is_staff=True, is_superuser=True)

    def test_anonymous(self):
        self.assertRedirects(
            self.client.get(LIST_URL),
            f"/connexion/?next={LIST_URL}",
            fetch_redirect_response=False,
        )

    def test_resident_denied(self):
        log_in_verified(self.client, self.awa)
        for path in (LIST_URL, "/equipe/journal/", "/guide/", "/equipe/nouvelle-page/"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 403)

    def test_staff_without_verified_passkey(self):
        # Session opened without a passkey: it must be confirmed with a passkey.
        self.client.force_login(self.front_desk)
        self.assertRedirects(
            self.client.get(LIST_URL),
            f"{reverse('access:confirm')}?next=%2Fequipe%2Fresidents%2F",
            fetch_redirect_response=False,
        )

    def test_verified_staff(self):
        log_in_verified(self.client, self.front_desk)
        self.assertEqual(self.client.get(LIST_URL).status_code, 200)

    def test_passkey_login_then_staff_area(self):
        phone = SoftwareAuthenticator()
        phone.register(self.front_desk)
        options = self.client.post(reverse("access:verify_begin")).json()
        response = self.client.post(
            f"{reverse('access:verify_complete')}?next={LIST_URL}",
            data=json.dumps(phone.get(options)),
            content_type="application/json",
        )
        self.assertEqual(response.json()["redirect_url"], LIST_URL)
        self.assertEqual(self.client.get(LIST_URL).status_code, 200)


class AdminSiteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.front_desk = make_user("nadia", Role.FRONT_DESK)
        cls.admin = User.objects.create_superuser("marie", password="test-password")

    def test_staff_without_technical_access(self):
        # The front desk has no is_staff: the Django admin site is closed to them.
        log_in_verified(self.client, self.front_desk)
        self.assertEqual(self.client.get("/admin/").status_code, 403)

    def test_verified_admin(self):
        log_in_verified(self.client, self.admin)
        self.assertEqual(self.client.get("/admin/").status_code, 200)
        # The admin login page redirects to the next page, with no form.
        response = self.client.get("/admin/login/?next=/admin/accounts/user/")
        self.assertRedirects(response, "/admin/accounts/user/", fetch_redirect_response=False)
        response = self.client.get("/admin/login/?next=https://pirate.example/")
        self.assertRedirects(response, "/admin/", fetch_redirect_response=False)

    def test_unverified_admin(self):
        self.client.force_login(self.admin)
        response = self.client.get("/admin/")
        self.assertTrue(response["Location"].startswith(reverse("access:confirm")))

    def test_no_password_accepted(self):
        from django.contrib import admin
        from django.test import RequestFactory

        from accounts.backends import PermissionsOnlyBackend

        self.assertIsNone(authenticate(username="marie", password="test-password"))
        self.assertIsNone(
            PermissionsOnlyBackend().authenticate(None, username="marie", password="test-password")
        )
        # Even when called directly, the admin login has no form.
        request = RequestFactory().post(
            "/admin/login/", {"username": "marie", "password": "test-password"}
        )
        request.user = AnonymousUser()
        request.user.is_verified = lambda: False
        response = admin.site.login(request)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/connexion/"))

    def test_role_permissions_still_apply(self):
        self.assertTrue(self.front_desk.has_perm("accounts.manage_residents"))
        self.assertFalse(make_user("awa").has_perm("accounts.manage_residents"))

    @override_settings(ADMIN_URL="gestion-7f3k/")
    def test_admin_url_check(self):
        from access.checks import admin_url_not_default, admin_url_not_taken

        self.assertEqual(admin_url_not_default(None), [])
        self.assertEqual(admin_url_not_taken(None), [])
        with self.settings(ADMIN_URL="admin/"):
            self.assertEqual(admin_url_not_default(None)[0].id, "access.W001")
        # Review T14: a URL already taken would hide a page, or loop forever.
        for url in ("connexion/", "equipe/", "activer/x/", "guide/", "/"):
            with self.subTest(url=url), self.settings(ADMIN_URL=url):
                self.assertEqual(admin_url_not_taken(None)[0].id, "access.E001")
