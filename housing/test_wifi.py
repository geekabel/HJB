"""Wifi access of the rooms: encryption, recording, cuts (card T15)."""

import io
from datetime import date, timedelta

from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.management import CommandError, call_command
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user
from audit.models import Action, AuditEntry
from residents.departure import record_departure

from . import wifi, wifi_crypto
from .checks import wifi_encryption_keys
from .models import DEFAULT_WIFI_ALPHABET, Floor, Room, Stay, WifiAccess, WifiSettings
from .services import assign_room

KEY_A = Fernet.generate_key().decode()
KEY_B = Fernet.generate_key().decode()


class CryptoTests(TestCase):
    def test_round_trip_and_nothing_in_clear(self):
        token = wifi_crypto.encrypt("Soleil-2026!")
        self.assertNotIn("Soleil", token)
        self.assertEqual(wifi_crypto.decrypt(token), "Soleil-2026!")
        # Two encryptions of the same password differ (random IV).
        self.assertNotEqual(token, wifi_crypto.encrypt("Soleil-2026!"))

    def test_wrong_key(self):
        with override_settings(WIFI_ENCRYPTION_KEYS=[KEY_A]):
            token = wifi_crypto.encrypt("Soleil-2026!")
        with (
            override_settings(WIFI_ENCRYPTION_KEYS=[KEY_B]),
            self.assertRaises(wifi_crypto.WifiDecryptionError),
        ):
            wifi_crypto.decrypt(token)

    def test_missing_or_invalid_keys(self):
        for keys in ([], ["not-a-fernet-key"]):
            with self.subTest(keys=keys), override_settings(WIFI_ENCRYPTION_KEYS=keys):
                with self.assertRaises(ImproperlyConfigured):
                    wifi_crypto.encrypt("x" * 8)
                self.assertEqual(wifi_encryption_keys(None)[0].id, "housing.E001")
        with override_settings(WIFI_ENCRYPTION_KEYS=[KEY_A]):
            self.assertEqual(wifi_encryption_keys(None), [])


class WifiTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.f3 = Floor.objects.create(number=3)
        cls.r312 = Room.objects.create(number="312", floor=cls.f3)
        cls.r304 = Room.objects.create(number="304", floor=cls.f3)
        cls.ines = make_user("ines", first_name="Inès", last_name="Martin")
        cls.nadia = make_user("nadia", Role.FRONT_DESK)

    def record(self, room=None, password="Soleil-2026!", **kwargs):
        room = room or self.r312
        kwargs.setdefault("replaces", wifi.current_access(room))
        return wifi.set_access(
            room,
            username=kwargs.pop("username", "ch312-ines"),
            password=password,
            expires_on=kwargs.pop("expires_on", wifi.default_expiry()),
            by=self.nadia,
            **kwargs,
        )


class ServiceTests(WifiTestCase):
    def test_generated_in_the_portal_format(self):
        # Default format: 6 characters, lowercase letters and digits (e.g. vre8th / 72ptmk).
        passwords = {wifi.generate_password() for _ in range(20)}
        self.assertEqual(len(passwords), 20)
        for value in passwords | {wifi.generate_username()}:
            self.assertEqual(len(value), 6)
            self.assertTrue(set(value) <= set(DEFAULT_WIFI_ALPHABET))
        self.assertFalse(set("Il0O1") & set(DEFAULT_WIFI_ALPHABET))

    def test_format_changed_by_an_administrator(self):
        settings_row = WifiSettings.load()
        settings_row.username_length = 8
        settings_row.password_length = 12
        settings_row.alphabet = "ABCDEFGHJK23456789"
        settings_row.save()
        self.assertEqual(len(wifi.generate_username()), 8)
        password = wifi.generate_password()
        self.assertEqual(len(password), 12)
        self.assertTrue(set(password) <= set("ABCDEFGHJK23456789"))

    def test_generated_username_is_free(self):
        self.record(username="aaaaaa")
        settings_row = WifiSettings.load()
        settings_row.alphabet = "ab23456789"
        settings_row.username_length = 1
        settings_row.save()
        WifiAccess.objects.filter(username="aaaaaa").update(username="a")
        self.assertNotEqual(wifi.generate_username(), "a")

    def test_check_credential(self):
        for value in ("vre8th", "72ptmk", "Soleil-2026!", "x" * 64):
            self.assertEqual(wifi.check_credential(value), "", value)
        self.assertEqual(wifi.check_credential("ab c"), "Les espaces ne sont pas permis.")
        self.assertIn("de 4 à 64", wifi.check_credential("abc"))
        self.assertIn("de 4 à 64", wifi.check_credential("x" * 65))

    def test_settings_row(self):
        settings_row = WifiSettings.load()
        self.assertEqual(settings_row.pk, 1)
        self.assertEqual(WifiSettings.load().pk, 1)
        settings_row.alphabet = "aabbccddeeffgghhiijj"
        settings_row.save()
        self.assertEqual(WifiSettings.load().alphabet, "abcdefghij")
        for alphabet, message in (("abc def ghij", "espace"), ("abcdefghi", "10 caractères")):
            settings_row.alphabet = alphabet
            with (
                self.subTest(alphabet=alphabet),
                self.assertRaisesMessage(ValidationError, message),
            ):
                settings_row.full_clean()

    def test_one_active_access_per_username(self):
        self.record(username="vre8th")
        with self.assertRaises(ValidationError):
            self.record(room=self.r304, username="vre8th")

    def test_default_expiry_one_year(self):
        self.assertEqual(wifi.default_expiry(date(2026, 11, 5)), date(2027, 11, 5))

    def test_record_and_audit(self):
        access = self.record(generated=True)
        access.refresh_from_db()
        self.assertTrue(access.active)
        self.assertNotIn("Soleil", access.encrypted_password)
        self.assertEqual(wifi_crypto.decrypt(access.encrypted_password), "Soleil-2026!")
        entry = AuditEntry.objects.get(action=Action.WIFI_ACCESS_SET)
        self.assertEqual(entry.actor, self.nadia)
        self.assertTrue(entry.summary().startswith("Chambre 312, valable jusqu'au "))
        self.assertTrue(entry.summary().endswith("Mot de passe généré."))
        self.assertNotIn("Soleil", str(entry.details))

    def test_renewal_keeps_history(self):
        old = self.record()
        new = self.record(password="Lune-2027-ok")
        old.refresh_from_db()
        self.assertFalse(old.active)
        self.assertEqual(old.end_reason, WifiAccess.EndReason.RENEWED)
        self.assertEqual(wifi.current_access(self.r312), new)

    def test_one_active_access_per_room(self):
        self.record()
        with self.assertRaises(IntegrityError), transaction.atomic():
            WifiAccess.objects.create(
                room=self.r312,
                username="x",
                encrypted_password="x",
                expires_on=wifi.default_expiry(),
            )

    def test_expiry_after_creation(self):
        with self.assertRaises(ValidationError):
            self.record(expires_on=timezone.localdate())
        self.assertFalse(WifiAccess.objects.exists())

    def test_reveal_logs_each_display(self):
        access = self.record()
        admin = make_user("marie", Role.ADMIN)
        self.assertEqual(wifi.reveal_password(access, by=admin), "Soleil-2026!")
        wifi.reveal_password(access, by=admin)
        entries = AuditEntry.objects.filter(action=Action.WIFI_PASSWORD_SHOWN)
        self.assertEqual(entries.count(), 2)
        self.assertEqual(entries.first().summary(), "Chambre 312.")

    def test_renew_soon_and_expired(self):
        access = self.record(expires_on=timezone.localdate() + timedelta(days=12))
        self.assertTrue(access.renew_soon)
        self.assertFalse(access.is_expired)
        WifiAccess.objects.filter(pk=access.pk).update(
            created_on=timezone.localdate() - timedelta(days=400),
            expires_on=timezone.localdate() - timedelta(days=1),
        )
        access.refresh_from_db()
        self.assertTrue(access.is_expired)
        self.assertFalse(access.renew_soon)


class RecordingChecksTests(WifiTestCase):
    """Cases found by the independent review of T15."""

    def test_refused_when_the_stay_is_over(self):
        stay = Stay.objects.create(resident=self.ines, room=self.r312, arrival=date(2026, 9, 1))
        record_departure(self.ines, timezone.localdate())
        with self.assertRaises(ValidationError) as error:
            self.record(stay=stay)
        self.assertEqual(error.exception.code, "no_current_stay")
        self.assertFalse(WifiAccess.objects.exists())

    def test_refused_when_another_access_was_recorded_meanwhile(self):
        seen = self.record()
        self.record(password="Lune-2027-ok", replaces=seen)  # first click
        with self.assertRaises(ValidationError) as error:
            self.record(password="Mars-2028-ok", replaces=seen)  # second click
        self.assertEqual(error.exception.code, "access_changed")
        self.assertEqual(
            wifi_crypto.decrypt(wifi.current_access(self.r312).encrypted_password), "Lune-2027-ok"
        )
        with self.assertRaises(ValidationError):
            self.record(replaces=None)  # the form showed no access, but there is one


class CutTests(WifiTestCase):
    def test_departure_cuts_the_room_access(self):
        Stay.objects.create(resident=self.ines, room=self.r312, arrival=date(2026, 9, 1))
        access = self.record()
        record_departure(self.ines, timezone.localdate())
        access.refresh_from_db()
        self.assertFalse(access.active)
        self.assertEqual(access.end_reason, WifiAccess.EndReason.DEPARTURE)
        entry = AuditEntry.objects.get(action=Action.RESIDENT_DEPARTED)
        self.assertEqual(entry.details["wifi_cut"], 1)
        self.assertIn("Accès wifi coupé.", entry.summary())

    def test_departure_without_access(self):
        Stay.objects.create(resident=self.ines, room=self.r312, arrival=date(2026, 9, 1))
        record_departure(self.ines, timezone.localdate())
        entry = AuditEntry.objects.get(action=Action.RESIDENT_DEPARTED)
        self.assertNotIn("wifi", entry.summary())

    def test_same_day_room_fix_cuts_the_first_room(self):
        Stay.objects.create(resident=self.ines, room=self.r312, arrival=timezone.localdate())
        access = self.record()
        assign_room(self.ines, self.r304, timezone.localdate())
        access.refresh_from_db()
        self.assertFalse(access.active)
        self.assertEqual(access.end_reason, WifiAccess.EndReason.MOVE)

    def test_room_change_cuts_the_old_room(self):
        Stay.objects.create(resident=self.ines, room=self.r312, arrival=date(2026, 9, 1))
        access = self.record()
        assign_room(self.ines, self.r304, timezone.localdate())
        access.refresh_from_db()
        self.assertFalse(access.active)
        self.assertEqual(access.end_reason, WifiAccess.EndReason.MOVE)


class RotationTests(WifiTestCase):
    def test_rotate_to_a_new_key(self):
        with override_settings(WIFI_ENCRYPTION_KEYS=[KEY_A]):
            access = self.record()
        with override_settings(WIFI_ENCRYPTION_KEYS=[KEY_B, KEY_A]):
            out = io.StringIO()
            call_command("rotate_wifi_keys", stdout=out)
            self.assertIn("1 mot de passe chiffré de nouveau.", out.getvalue())
        access.refresh_from_db()
        with override_settings(WIFI_ENCRYPTION_KEYS=[KEY_B]):
            self.assertEqual(wifi_crypto.decrypt(access.encrypted_password), "Soleil-2026!")

    def test_unreadable_password_changes_nothing(self):
        # One password readable with the new key list, one not: nothing is changed at all.
        with override_settings(WIFI_ENCRYPTION_KEYS=[KEY_A]):
            readable = self.record()
        other_key = Fernet.generate_key().decode()
        with override_settings(WIFI_ENCRYPTION_KEYS=[other_key]):
            unreadable = self.record(room=self.r304, username="ch304")
        before = dict(WifiAccess.objects.values_list("pk", "encrypted_password"))
        with (
            override_settings(WIFI_ENCRYPTION_KEYS=[KEY_B, KEY_A]),
            self.assertRaisesMessage(CommandError, "rien n'est changé"),
        ):
            call_command("rotate_wifi_keys", stdout=io.StringIO())
        after = dict(WifiAccess.objects.values_list("pk", "encrypted_password"))
        self.assertEqual(after, before)
        self.assertIn(readable.pk, after)
        self.assertIn(unreadable.pk, after)


class WifiSettingsAdminTests(TestCase):
    """The format of the portal is changed in the admin site (card T15b)."""

    @classmethod
    def setUpTestData(cls):
        cls.marie = make_user("marie", Role.ADMIN, is_staff=True)
        cls.nadia = make_user("nadia", Role.FRONT_DESK, is_staff=True)

    def test_admin_changes_the_format(self):
        log_in_verified(self.client, self.marie)
        response = self.client.get(reverse("admin:housing_wifisettings_changelist"))
        change = reverse("admin:housing_wifisettings_change", args=[1])
        self.assertRedirects(response, change)
        response = self.client.get(change)
        self.assertContains(response, "Format des accès générés")
        self.assertNotContains(response, "deletelink")
        response = self.client.post(
            change,
            {
                "network_name": "HJB-Residents",
                "username_length": "8",
                "password_length": "12",
                "alphabet": "abcdefghijkmnpqrstuvwxyz23456789",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(wifi.generate_username()), 8)
        self.assertEqual(len(wifi.generate_password()), 12)
        self.assertEqual(WifiSettings.objects.count(), 1)
        # Out of bounds: refused with a message, nothing changed.
        response = self.client.post(
            change,
            {"username_length": "3", "password_length": "64", "alphabet": "abc"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(WifiSettings.load().username_length, 8)

    def test_front_desk_cannot_change_it(self):
        log_in_verified(self.client, self.nadia)
        for url in (
            reverse("admin:housing_wifisettings_changelist"),
            reverse("admin:housing_wifisettings_change", args=[1]),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(
            self.client.post(
                reverse("admin:housing_wifisettings_change", args=[1]), {"username_length": "4"}
            ).status_code,
            403,
        )
