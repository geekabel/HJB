"""Installable application (card T18)."""

import json

from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse

from accounts.tests.helpers import log_in_verified, make_user
from tools.html_capture import save_page


class ManifestTests(TestCase):
    def test_manifest(self):
        response = self.client.get("/manifest.webmanifest")
        self.assertEqual(response["Content-Type"], "application/manifest+json")
        data = json.loads(response.content)
        # Chromium installability (MDN): name, 192 and 512 icons, start_url, display.
        self.assertEqual(data["name"], "HJB Résidence")
        self.assertEqual(data["start_url"], "/")
        self.assertEqual(data["scope"], "/")
        self.assertEqual(data["display"], "standalone")
        sizes = {icon["sizes"] for icon in data["icons"]}
        self.assertEqual(sizes, {"192x192", "512x512"})
        self.assertIn("maskable", [icon.get("purpose") for icon in data["icons"]])
        for icon in data["icons"]:
            name = icon["src"].removeprefix("/static/")
            self.assertTrue(finders.find(name), name)

    def test_every_page_links_it(self):
        response = self.client.get(reverse("access:login"))
        self.assertContains(response, '<link rel="manifest" href="/manifest.webmanifest">')
        self.assertContains(response, 'rel="apple-touch-icon"')
        self.assertContains(response, "ui/js/app.js")

    def test_favicon(self):
        response = self.client.get("/favicon.ico")
        self.assertRedirects(
            response, "/static/ui/icons/favicon.ico", status_code=301, fetch_redirect_response=False
        )
        self.assertTrue(finders.find("ui/icons/favicon.ico"))


class ServiceWorkerTests(TestCase):
    def test_served_from_the_root_and_never_cached(self):
        response = self.client.get("/sw.js")
        self.assertEqual(response["Content-Type"], "text/javascript; charset=utf-8")
        self.assertEqual(response["Cache-Control"], "no-cache")
        body = response.content.decode()
        self.assertIn('const OFFLINE_URL = "/hors-ligne/";', body)
        self.assertIn('"/static/ui/css/hjb.css"', body)
        self.assertRegex(body, r'const CACHE = "hjb-offline-[0-9a-f]{12}";')

    def test_only_public_files_are_kept(self):
        body = self.client.get("/sw.js").content.decode()
        precache = body.split("const PRECACHE = ")[1].split(";")[0]
        for private in ("/wifi/", "/equipe/", "/connexion/", "/activer/"):
            self.assertNotIn(private, precache)


class PagesTests(TestCase):
    def test_offline_page_is_public(self):
        response = self.client.get(reverse("offline"))
        save_page("ui-offline", response)
        self.assertContains(response, "Pas de connexion")
        self.assertNotContains(response, 'class="resident-nav"')

    def test_offline_page_shows_no_personal_data(self):
        user = make_user("ines", first_name="Inès")
        log_in_verified(self.client, user)
        response = self.client.get(reverse("offline"))
        self.assertNotContains(response, "Inès")

    def test_install_page(self):
        response = self.client.get(reverse("install"))
        save_page("ui-install", response)
        self.assertContains(response, "Sur l'écran d'accueil")
        self.assertContains(response, "data-install-button")

    def test_home_shortcut(self):
        log_in_verified(self.client, make_user("ines"))
        response = self.client.get(reverse("home"))
        self.assertContains(response, 'href="/installer/" data-hide-when-installed')
