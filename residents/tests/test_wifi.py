"""Wifi of the room, staff side: record, generate, show (card T15)."""

import time
from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from access.session_policy import CONFIRMED_AT_KEY
from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user
from audit.models import Action, AuditEntry
from housing import wifi, wifi_crypto
from housing.models import Floor, Room, Stay, WifiAccess
from tools.html_capture import save_page

PASSWORD = "Soleil-2026!"


class WifiPagesTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.front_desk = make_user("nadia", Role.FRONT_DESK, first_name="Nadia")
        cls.admin = make_user("marie", Role.ADMIN, first_name="Marie")
        cls.educator = make_user("sam", Role.EDUCATOR)
        cls.f3 = Floor.objects.create(number=3)
        cls.r312 = Room.objects.create(number="312", floor=cls.f3)
        cls.ines = make_user("ines", first_name="Inès", last_name="Martin")
        cls.lucas = make_user("lucas", first_name="Lucas")  # no room
        Stay.objects.create(resident=cls.ines, room=cls.r312, arrival=date(2026, 9, 1))

    def log_in(self, user, confirmed=True):
        log_in_verified(self.client, user)
        if confirmed:
            session = self.client.session
            session[CONFIRMED_AT_KEY] = time.time()
            session.save()

    def record(self, **kwargs):
        return wifi.set_access(
            self.r312,
            username="ch312-ines",
            password=PASSWORD,
            expires_on=kwargs.pop("expires_on", wifi.default_expiry()),
            by=self.front_desk,
        )

    def url(self, name, resident=None):
        return reverse(f"residents:{name}", args=[(resident or self.ines).pk])

    def form_page(self):
        response = self.client.get(self.url("wifi_access"))
        return response, response.context["token"]


class RecordTests(WifiPagesTestCase):
    def test_needs_a_recent_passkey_confirmation(self):
        self.log_in(self.front_desk, confirmed=False)
        response = self.client.get(self.url("wifi_access"))
        self.assertTrue(response["Location"].startswith(reverse("access:confirm")))

    def test_form(self):
        self.log_in(self.front_desk)
        response, _ = self.form_page()
        save_page("residents-wifi-access", response)
        self.assertContains(response, f'value="{wifi.default_expiry():%Y-%m-%d}"')
        # No access yet: the username is empty, to type or to generate.
        self.assertNotContains(response, 'name="username" value=')
        self.assertContains(response, "6 caractères pour l'identifiant, 6 pour le mot de passe")

    def test_form_of_a_renewal_keeps_the_username(self):
        self.record()
        self.log_in(self.front_desk)
        response, _ = self.form_page()
        self.assertContains(response, 'value="ch312-ines"')

    def test_record_the_portal_format(self):
        # The real format of the residence portal: 6 and 6 characters.
        self.log_in(self.front_desk)
        _, token = self.form_page()
        data = {"token": token, "username": "vre8th", "password": "72ptmk"}
        data["expires_on"] = f"{wifi.default_expiry():%Y-%m-%d}"
        response = self.client.post(self.url("wifi_access"), data)
        self.assertEqual(response.status_code, 302)
        access = WifiAccess.objects.get()
        self.assertEqual(access.username, "vre8th")
        self.assertEqual(wifi_crypto.decrypt(access.encrypted_password), "72ptmk")

    def test_record_a_typed_password(self):
        self.log_in(self.front_desk)
        _, token = self.form_page()
        response = self.client.post(
            self.url("wifi_access"),
            {
                "token": token,
                "username": "ch312-ines",
                "password": PASSWORD,
                "expires_on": "2027-09-01",
            },
            follow=True,
        )
        self.assertRedirects(response, self.url("detail"))
        self.assertContains(response, "valable jusqu&#x27;au 01/09/2027")
        access = WifiAccess.objects.get()
        self.assertFalse(access.generated)
        self.assertEqual(wifi_crypto.decrypt(access.encrypted_password), PASSWORD)
        # The profile shows the username and the date, never the password.
        save_page("residents-detail-wifi", response)
        self.assertContains(response, "ch312-ines")
        self.assertNotContains(response, PASSWORD)

    def test_generate_once(self):
        self.log_in(self.front_desk)
        _, token = self.form_page()
        data = {
            "token": token,
            "username": "ch312-ines",
            "password": "",
            "expires_on": f"{wifi.default_expiry():%Y-%m-%d}",
        }
        response = self.client.post(self.url("wifi_access"), data)
        access = WifiAccess.objects.get()
        self.assertTrue(access.generated)
        self.assertEqual(access.username, "ch312-ines")
        password = wifi_crypto.decrypt(access.encrypted_password)
        self.assertEqual(len(password), 6)
        self.assertContains(response, password)
        self.assertContains(response, "Ce mot de passe ne s'affichera qu'une fois")
        self.assertIn("no-store", response["Cache-Control"])
        # Reloading the page sends the same form again: nothing new is generated.
        response = self.client.post(self.url("wifi_access"), data, follow=True)
        self.assertContains(response, "Ce formulaire a déjà servi")
        self.assertEqual(WifiAccess.objects.count(), 1)

    def test_generate_both(self):
        self.log_in(self.front_desk)
        _, token = self.form_page()
        data = {"token": token, "username": "", "password": ""}
        data["expires_on"] = f"{wifi.default_expiry():%Y-%m-%d}"
        response = self.client.post(self.url("wifi_access"), data)
        save_page("residents-wifi-generated", response)
        access = WifiAccess.objects.get()
        self.assertEqual(len(access.username), 6)
        self.assertContains(response, access.username)
        self.assertContains(response, wifi_crypto.decrypt(access.encrypted_password))
        self.assertContains(response, "l'identifiant et le mot de passe")

    def test_generate_the_username_only(self):
        self.log_in(self.front_desk)
        _, token = self.form_page()
        data = {"token": token, "username": "", "password": "72ptmk"}
        data["expires_on"] = f"{wifi.default_expiry():%Y-%m-%d}"
        response = self.client.post(self.url("wifi_access"), data)
        access = WifiAccess.objects.get()
        self.assertTrue(access.generated is False)
        self.assertContains(response, access.username)
        # The typed password is never shown back.
        self.assertNotContains(response, "72ptmk")
        self.assertContains(response, "Recopiez maintenant l'identifiant sur")

    def test_invalid_input(self):
        self.log_in(self.front_desk)
        _, token = self.form_page()
        response = self.client.post(
            self.url("wifi_access"),
            {
                "token": token,
                "username": "ch312-ines",
                "password": "abc",
                "expires_on": f"{timezone.localdate():%Y-%m-%d}",
            },
        )
        self.assertContains(response, "Il faut de 4 à 64 caractères.")
        # The typed password is never sent back in the page, which is never cached.
        self.assertNotContains(response, 'value="abc"')
        self.assertIn("no-store", response["Cache-Control"])
        self.assertContains(response, "La date doit être dans le futur.")
        self.assertFalse(WifiAccess.objects.exists())
        # The token stays valid: the corrected form can be sent.
        response = self.client.post(
            self.url("wifi_access"),
            {
                "token": token,
                "username": "ch312-ines",
                "password": PASSWORD,
                "expires_on": f"{wifi.default_expiry():%Y-%m-%d}",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(WifiAccess.objects.count(), 1)

    def test_resident_without_room(self):
        self.log_in(self.front_desk)
        response = self.client.get(self.url("wifi_access", self.lucas), follow=True)
        self.assertRedirects(response, self.url("detail", self.lucas))
        self.assertContains(response, "pas d&#x27;accès wifi à gérer")

    def test_educator_cannot_record(self):
        self.log_in(self.educator)
        self.assertEqual(self.client.get(self.url("wifi_access")).status_code, 403)


class RecordReviewTests(WifiPagesTestCase):
    """Cases found by the independent review of T15."""

    def post(self, token, **data):
        return self.client.post(
            self.url("wifi_access"),
            {
                "token": token,
                "username": "ch312-ines",
                "password": PASSWORD,
                "expires_on": f"{wifi.default_expiry():%Y-%m-%d}",
                **data,
            },
            follow=True,
        )

    def test_two_forms_open_at_once(self):
        self.log_in(self.front_desk)
        _, first = self.form_page()
        _, second = self.form_page()
        self.post(first)
        response = self.post(second)  # this form still showed "no access"
        self.assertContains(response, "vient d&#x27;être modifié par une autre demande")
        self.assertEqual(WifiAccess.objects.count(), 1)

    def test_form_opened_before_a_room_change(self):
        from housing.services import assign_room

        other = Room.objects.create(number="205", floor=self.f3)
        self.log_in(self.front_desk)
        _, token = self.form_page()
        assign_room(self.ines, other, timezone.localdate())
        response = self.post(token)
        self.assertContains(response, "la chambre a changé depuis")
        self.assertFalse(WifiAccess.objects.exists())

    def test_keys_not_configured(self):
        from django.test import override_settings

        self.log_in(self.front_desk)
        _, token = self.form_page()
        with override_settings(WIFI_ENCRYPTION_KEYS=[]), self.assertLogs("residents.views"):
            response = self.post(token)
        self.assertContains(response, "pas configuré sur le serveur")
        self.assertFalse(WifiAccess.objects.exists())

    def test_departure_without_wifi_says_nothing_about_it(self):
        self.log_in(self.front_desk)
        response = self.client.post(
            self.url("departure"), {"departure": f"{timezone.localdate():%Y-%m-%d}"}, follow=True
        )
        self.assertContains(response, "Le départ de Inès Martin est enregistré.")
        self.assertNotContains(response, "accès wifi de la chambre")


class ShowPasswordTests(WifiPagesTestCase):
    def setUp(self):
        self.access = self.record()

    def test_front_desk_cannot_show(self):
        self.log_in(self.front_desk)
        self.assertEqual(self.client.get(self.url("wifi_password")).status_code, 403)
        self.assertEqual(self.client.post(self.url("wifi_password")).status_code, 403)
        detail = self.client.get(self.url("detail"))
        self.assertNotContains(detail, "Afficher le mot de passe")
        self.assertContains(detail, "Renouveler l'accès</a>")

    def test_admin_shows_after_confirmation(self):
        self.log_in(self.admin, confirmed=False)
        response = self.client.get(self.url("wifi_password"))
        self.assertTrue(response["Location"].startswith(reverse("access:confirm")))
        self.log_in(self.admin)
        response = self.client.get(self.url("wifi_password"))
        save_page("residents-wifi-password", response)
        self.assertNotContains(response, PASSWORD)
        self.assertFalse(AuditEntry.objects.filter(action=Action.WIFI_PASSWORD_SHOWN).exists())
        response = self.client.post(self.url("wifi_password"))
        save_page("residents-wifi-password-shown", response)
        self.assertContains(response, PASSWORD)
        self.assertIn("no-store", response["Cache-Control"])
        entry = AuditEntry.objects.get(action=Action.WIFI_PASSWORD_SHOWN)
        self.assertEqual(entry.actor, self.admin)

    def test_unreadable_password(self):
        from cryptography.fernet import Fernet
        from django.test import override_settings

        self.log_in(self.admin)
        with (
            override_settings(WIFI_ENCRYPTION_KEYS=[Fernet.generate_key().decode()]),
            self.assertLogs("residents.views", "ERROR"),
        ):
            response = self.client.post(self.url("wifi_password"), follow=True)
        self.assertContains(response, "ne peut pas être déchiffré")
        self.assertFalse(AuditEntry.objects.filter(action=Action.WIFI_PASSWORD_SHOWN).exists())

    def test_no_active_access(self):
        WifiAccess.objects.update(active=False)
        self.log_in(self.admin)
        response = self.client.get(self.url("wifi_password"), follow=True)
        self.assertContains(response, "pas d&#x27;accès wifi actif")


class ListAndDepartureTests(WifiPagesTestCase):
    def test_list_column(self):
        self.record(expires_on=timezone.localdate() + timedelta(days=12))
        self.log_in(self.educator, confirmed=False)
        response = self.client.get(reverse("residents:list"))
        save_page("residents-list-wifi", response)
        self.assertContains(response, "Wifi jusqu'au</th>")
        self.assertContains(response, "dans 12 j")
        self.assertNotContains(response, PASSWORD)
        self.assertNotContains(response, "ch312-ines")

    def test_departure_message(self):
        self.record()
        self.log_in(self.front_desk)
        response = self.client.post(
            self.url("departure"), {"departure": f"{timezone.localdate():%Y-%m-%d}"}, follow=True
        )
        self.assertContains(response, "L&#x27;accès wifi de la chambre 312 est coupé")
        self.assertFalse(WifiAccess.objects.get().active)
