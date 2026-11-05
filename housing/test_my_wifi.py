"""Resident page "Mon wifi" (card T16)."""

import time
from datetime import date, timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from access.session_policy import CONFIRMED_AT_KEY
from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user
from audit.models import Action, AuditEntry
from tools.html_capture import save_page

from . import wifi
from .models import Floor, Room, Stay, WifiAccess, WifiSettings
from .views import time_left, validity_percent

URL = reverse("housing:my_wifi")
PASSWORD_URL = reverse("housing:my_wifi_password")


class MyWifiTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.nadia = make_user("nadia", Role.FRONT_DESK)
        f3 = Floor.objects.create(number=3)
        cls.r312 = Room.objects.create(number="312", floor=f3)
        cls.r304 = Room.objects.create(number="304", floor=f3)
        cls.ines = make_user("ines", first_name="Inès", last_name="Martin")
        cls.yanis = make_user("yanis", first_name="Yanis")
        Stay.objects.create(resident=cls.ines, room=cls.r312, arrival=date(2026, 9, 1))
        Stay.objects.create(resident=cls.yanis, room=cls.r304, arrival=date(2026, 9, 1))

    def record(self, room=None, **kwargs):
        room = room or self.r312
        return wifi.set_access(
            room,
            username=kwargs.pop("username", "vre8th"),
            password=kwargs.pop("password", "72ptmk"),
            expires_on=kwargs.pop("expires_on", wifi.default_expiry()),
            replaces=wifi.current_access(room),
            by=self.nadia,
        )

    def log_in(self, user=None, confirmed=False):
        log_in_verified(self.client, user or self.ines)
        session = self.client.session
        if confirmed:
            session[CONFIRMED_AT_KEY] = time.time()
        else:
            session.pop(CONFIRMED_AT_KEY, None)
        session.save()


class PageTests(MyWifiTestCase):
    def test_login_required(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("access:login"), response["Location"])

    def test_masked_by_default(self):
        settings_row = WifiSettings.load()
        settings_row.network_name = "HJB-Residents"
        settings_row.save()
        self.record()
        self.log_in()
        response = self.client.get(URL)
        save_page("housing-my-wifi", response)
        self.assertContains(response, "HJB-Residents")
        self.assertContains(response, "vre8th")
        self.assertNotContains(response, "72ptmk")
        self.assertContains(response, f'action="{PASSWORD_URL}"')
        self.assertContains(response, "encore 12 mois")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertFalse(AuditEntry.objects.filter(action=Action.WIFI_PASSWORD_SHOWN).exists())

    def test_network_name_not_set(self):
        self.record()
        self.log_in()
        response = self.client.get(URL)
        self.assertContains(response, "Demandez le nom du réseau à l'accueil.")

    def test_only_the_access_of_my_room(self):
        self.record(self.r304, username="k3pzqa", password="h7mwrd")
        self.log_in()
        response = self.client.get(URL)
        save_page("housing-my-wifi-not-ready", response)
        self.assertContains(response, "pas encore prêt")
        self.assertNotContains(response, "k3pzqa")
        self.assertEqual(self.client.get(PASSWORD_URL).status_code, 302)

    def test_no_room(self):
        lucas = make_user("lucas")
        self.log_in(lucas)
        response = self.client.get(URL)
        self.assertContains(response, "Vous n'avez pas de chambre")

    def test_expired_and_soon(self):
        access = self.record(expires_on=timezone.localdate() + timedelta(days=10))
        self.log_in()
        response = self.client.get(URL)
        self.assertContains(response, "se termine bientôt")
        self.assertContains(response, "encore 10 jours")
        self.assertContains(response, "validity validity--low")
        WifiAccess.objects.filter(pk=access.pk).update(
            created_on=timezone.localdate() - timedelta(days=400),
            expires_on=timezone.localdate() - timedelta(days=1),
        )
        response = self.client.get(URL)
        save_page("housing-my-wifi-expired", response)
        self.assertContains(response, "Votre accès a expiré.")

    def test_home_shortcut(self):
        self.log_in()
        self.assertContains(self.client.get(reverse("home")), f'href="{URL}"')


class ShowPasswordTests(MyWifiTestCase):
    def setUp(self):
        self.record()

    def test_needs_a_recent_passkey_confirmation(self):
        self.log_in()
        for method in (self.client.get, self.client.post):
            with self.subTest(method=method.__name__):
                response = method(PASSWORD_URL)
                self.assertTrue(response["Location"].startswith(reverse("access:confirm")))
                self.assertIn("next=%2Fwifi%2Fmot-de-passe%2F", response["Location"])
        self.assertFalse(AuditEntry.objects.filter(action=Action.WIFI_PASSWORD_SHOWN).exists())

    def test_shown_on_post_and_logged(self):
        self.log_in(confirmed=True)
        response = self.client.post(PASSWORD_URL)
        save_page("housing-my-wifi-shown", response)
        self.assertContains(response, "72ptmk")
        self.assertContains(response, 'data-copy="wifi-password"')
        self.assertContains(response, "Masquer le mot de passe")
        self.assertIn("no-store", response["Cache-Control"])
        entry = AuditEntry.objects.get(action=Action.WIFI_PASSWORD_SHOWN)
        self.assertEqual(entry.actor, self.ines)
        self.assertEqual(entry.summary(), "Chambre 312.")

    def test_get_never_shows_it(self):
        # Review of T16: back button, reload, prefetch or a link from elsewhere.
        self.log_in(confirmed=True)
        response = self.client.get(PASSWORD_URL, headers={"sec-purpose": "prefetch"}, follow=True)
        self.assertRedirects(response, URL)
        self.assertContains(response, "Appuyez sur « Afficher ».")
        self.assertNotContains(response, "72ptmk")
        self.assertFalse(AuditEntry.objects.filter(action=Action.WIFI_PASSWORD_SHOWN).exists())

    def test_unreadable_password(self):
        from cryptography.fernet import Fernet

        self.log_in(confirmed=True)
        with (
            override_settings(WIFI_ENCRYPTION_KEYS=[Fernet.generate_key().decode()]),
            self.assertLogs("housing.views", "ERROR"),
        ):
            response = self.client.post(PASSWORD_URL, follow=True)
        self.assertRedirects(response, URL)
        self.assertContains(response, "un nouvel accès")
        self.assertFalse(AuditEntry.objects.filter(action=Action.WIFI_PASSWORD_SHOWN).exists())


class OtherRoomTests(MyWifiTestCase):
    """Review of T16: a resident never sees the access of another room."""

    def setUp(self):
        self.record()

    def test_after_a_room_change(self):
        from .services import assign_room

        self.log_in(confirmed=True)
        assign_room(self.ines, Room.objects.create(number="305", floor=self.r312.floor))
        response = self.client.get(URL)
        self.assertContains(response, "pas encore prêt")
        self.assertNotContains(response, "vre8th")
        response = self.client.post(PASSWORD_URL)
        self.assertRedirects(response, URL)

    def test_after_a_departure(self):
        from residents.departure import record_departure

        self.log_in(confirmed=True)
        record_departure(self.ines, timezone.localdate())
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("access:login"), response["Location"])

    def test_staff_without_a_room(self):
        self.log_in(self.nadia, confirmed=True)
        response = self.client.get(URL)
        self.assertContains(response, "Vous n'avez pas de chambre")
        self.assertRedirects(self.client.post(PASSWORD_URL), URL)


class TextTests(TestCase):
    def test_time_left(self):
        self.assertEqual(time_left(-1), "expiré")
        self.assertEqual(time_left(0), "dernier jour")
        self.assertEqual(time_left(1), "encore 1 jour")
        self.assertEqual(time_left(59), "encore 59 jours")
        self.assertEqual(time_left(300), "encore 10 mois")

    def test_validity_percent(self):
        access = WifiAccess(
            created_on=timezone.localdate() - timedelta(days=73),
            expires_on=timezone.localdate() + timedelta(days=292),
        )
        self.assertEqual(validity_percent(access), 80)
        access.expires_on = timezone.localdate() - timedelta(days=5)
        self.assertEqual(validity_percent(access), 0)
