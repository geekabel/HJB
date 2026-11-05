"""Wifi access of the rooms: encryption, recording, cuts (card T15)."""

import io
from datetime import date, timedelta

from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.management import CommandError, call_command
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.roles import Role
from accounts.tests.helpers import make_user
from audit.models import Action, AuditEntry
from residents.departure import record_departure

from . import wifi, wifi_crypto
from .checks import wifi_encryption_keys
from .models import Floor, Room, Stay, WifiAccess
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
        return wifi.set_access(
            room or self.r312,
            username=kwargs.pop("username", "ch312-ines"),
            password=password,
            expires_on=kwargs.pop("expires_on", wifi.default_expiry()),
            by=self.nadia,
            **kwargs,
        )


class ServiceTests(WifiTestCase):
    def test_generated_password(self):
        passwords = {wifi.generate_password() for _ in range(20)}
        self.assertEqual(len(passwords), 20)
        for password in passwords:
            self.assertEqual(len(password), wifi.GENERATED_LENGTH)
            self.assertTrue(set(password) <= set(wifi.ALPHABET))
        self.assertFalse(set("Il0O1") & set(wifi.ALPHABET))

    def test_suggested_username(self):
        self.assertEqual(wifi.suggest_username(self.r312, self.ines), "ch312-ines")
        self.assertEqual(wifi.suggest_username(self.r312), "ch312")

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
        with override_settings(WIFI_ENCRYPTION_KEYS=[KEY_A]):
            access = self.record()
        before = WifiAccess.objects.get(pk=access.pk).encrypted_password
        with (
            override_settings(WIFI_ENCRYPTION_KEYS=[KEY_B]),
            self.assertRaisesMessage(CommandError, "rien n'est changé"),
        ):
            call_command("rotate_wifi_keys", stdout=io.StringIO())
        self.assertEqual(WifiAccess.objects.get(pk=access.pk).encrypted_password, before)
