"""Security headers on every page (card T37)."""

from django.test import TestCase
from django.urls import reverse

from accounts.tests.helpers import log_in_verified, make_user


class SecurityHeadersTests(TestCase):
    def test_public_and_private_pages(self):
        resident = make_user("ines")
        pages = [(None, reverse("access:login")), (None, reverse("privacy"))]
        pages += [(resident, reverse("account"))]
        for user, url in pages:
            with self.subTest(url=url):
                if user:
                    log_in_verified(self.client, user)
                response = self.client.get(url)
                policy = response.headers["Content-Security-Policy"]
                self.assertIn("default-src 'none'", policy)
                self.assertIn("script-src 'self'", policy)
                self.assertIn("frame-ancestors 'none'", policy)
                self.assertNotIn("data:", policy)
                self.assertNotIn("unsafe-inline", policy)
                self.assertIn("camera=()", response.headers["Permissions-Policy"])
                self.assertEqual(response.headers["X-Frame-Options"], "DENY")
                self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                self.assertEqual(response.headers["Referrer-Policy"], "same-origin")
                self.assertEqual(response.headers["Cross-Origin-Opener-Policy"], "same-origin")

    def test_service_worker_too(self):
        response = self.client.get(reverse("service_worker"))
        self.assertIn("Content-Security-Policy", response.headers)

    def test_headers_also_on_a_refusal_of_the_staff_area(self):
        log_in_verified(self.client, make_user("demo"))
        response = self.client.get(reverse("audit:list"))
        self.assertIn(response.status_code, (302, 403))
        self.assertIn("Content-Security-Policy", response.headers)
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertIn("Permissions-Policy", response.headers)

    def test_personal_pages_are_never_cached(self):
        log_in_verified(self.client, make_user("ines"))
        response = self.client.get(reverse("account"))
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertIn("private", response.headers["Cache-Control"])
        # Anonymous public page: no such header needed.
        self.client.logout()
        self.assertNotIn("no-store", self.client.get(reverse("privacy")).get("Cache-Control", ""))
