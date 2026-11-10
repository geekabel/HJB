"""Import of the existing wifi list (card T15b)."""

import io
import time
from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from access.session_policy import CONFIRMED_AT_KEY
from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user
from audit.models import Action, AuditEntry
from housing import wifi, wifi_crypto
from housing.models import Floor, Room, Stay, WifiAccess
from residents.departure import record_departure
from tools.html_capture import save_page

NEXT_YEAR = (timezone.localdate() + timedelta(days=300)).strftime("%d/%m/%Y")


def csv_file(*lines, name="wifi.csv"):
    content = "\r\n".join(lines).encode("utf-8")
    return SimpleUploadedFile(name, content, content_type="text/csv")


class WifiImportTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user("marie", Role.ADMIN, first_name="Marie")
        cls.front_desk = make_user("nadia", Role.FRONT_DESK)
        f3 = Floor.objects.create(number=3)
        cls.r312 = Room.objects.create(number="312", floor=f3)
        cls.r304 = Room.objects.create(number="304", floor=f3)
        cls.r305 = Room.objects.create(number="305", floor=f3)  # free
        cls.ines = make_user("ines", first_name="Inès", last_name="Martin")
        cls.yanis = make_user("yanis", first_name="Yanis", last_name="Traoré")
        Stay.objects.create(resident=cls.ines, room=cls.r312, arrival=date(2026, 9, 1))
        Stay.objects.create(resident=cls.yanis, room=cls.r304, arrival=date(2026, 9, 1))

    def log_in(self, user=None, confirmed=True):
        log_in_verified(self.client, user or self.admin)
        if confirmed:
            session = self.client.session
            session[CONFIRMED_AT_KEY] = time.time()
            session.save()

    def upload(self, file):
        return self.client.post(reverse("residents:wifi_import"), {"file": file}, follow=True)

    def confirm(self, response):
        return self.client.post(
            reverse("residents:wifi_import_preview"),
            {
                "token": response.context["token"],
                "state": response.context["state"],
                "action": "import",
            },
            follow=True,
        )


class AccessTests(WifiImportTestCase):
    def test_front_desk_cannot_import(self):
        self.log_in(self.front_desk)
        for name in ("wifi_import", "wifi_import_preview", "wifi_import_template"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(f"residents:{name}")).status_code, 403)
        response = self.client.get(reverse("residents:list"))
        self.assertNotContains(response, "La liste wifi</a>")

    def test_admin_needs_a_recent_confirmation(self):
        self.log_in(confirmed=False)
        response = self.client.get(reverse("residents:wifi_import"))
        self.assertTrue(response["Location"].startswith(reverse("access:confirm")))

    def test_upload_page_and_template(self):
        self.log_in()
        response = self.client.get(reverse("residents:wifi_import"))
        save_page("residents-wifi-import", response)
        self.assertContains(response, "Colonnes attendues")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertContains(self.client.get(reverse("residents:list")), "La liste wifi</a>")
        response = self.client.get(reverse("residents:wifi_import_template"))
        self.assertEqual(
            response.content.decode("utf-8-sig"),
            "Identifiant;Mot de passe;Chambre;Résident;Valable jusqu'au\r\n",
        )


class ImportTests(WifiImportTestCase):
    def test_import_the_list(self):
        self.log_in()
        response = self.upload(
            csv_file(
                "Identifiant;Mot de passe;Chambre;Résident;Valable jusqu'au",
                f"vre8th;72ptmk;312;Inès Martin;{NEXT_YEAR}",
                "k3pzqa;h7mwrd;304;Traoré;",
            )
        )
        self.assertRedirects(response, reverse("residents:wifi_import_preview"))
        save_page("residents-wifi-import-preview", response)
        self.assertEqual(response.context["ready_count"], 2)
        # The passwords are not in the page, nor in clear in the session.
        self.assertNotContains(response, "72ptmk")
        self.assertNotIn("72ptmk", str(dict(self.client.session)))
        self.assertContains(response, "Inès Martin")
        self.assertContains(response, "Dans un an")

        response = self.confirm(response)
        self.assertRedirects(response, reverse("residents:list"))
        self.assertContains(response, "2 accès wifi enregistrés.")
        access = WifiAccess.objects.get(room=self.r312)
        self.assertEqual(access.username, "vre8th")
        self.assertEqual(wifi_crypto.decrypt(access.encrypted_password), "72ptmk")
        self.assertEqual(f"{access.expires_on:%d/%m/%Y}", NEXT_YEAR)
        self.assertFalse(access.generated)
        other = WifiAccess.objects.get(room=self.r304)
        self.assertEqual(other.expires_on, wifi.default_expiry())
        entries = AuditEntry.objects.filter(action=Action.WIFI_ACCESS_SET, actor=self.admin)
        self.assertEqual(entries.count(), 2)
        # The preview is used once.
        self.assertNotIn("wifi_import", self.client.session)

    def test_excel_file(self):
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Chambre", "Identifiant", "Mot de passe"])
        sheet.append([312, "vre8th", 123456])  # a password typed as a number
        sheet.append([118, "k3pzqa", 2.34e58])  # turned into a number by Excel
        content = io.BytesIO()
        workbook.save(content)
        self.log_in()
        response = self.upload(SimpleUploadedFile("wifi.xlsx", content.getvalue()))
        self.assertEqual(response.context["ready_count"], 1)
        self.assertContains(response, "Le mot de passe a été lu comme un nombre.")
        self.assertContains(response, "Le mot de passe a été transformé en nombre par Excel.")
        # Review of T15b: the value of a password never appears, even in a message.
        self.assertNotContains(response, "123456")
        self.assertNotIn("123456", str(dict(self.client.session)))
        self.confirm(response)
        access = WifiAccess.objects.get()
        self.assertEqual(wifi_crypto.decrypt(access.encrypted_password), "123456")

    def test_errors_and_warnings(self):
        wifi.set_access(
            self.r304,
            username="taken1",
            password="abcdef",
            expires_on=wifi.default_expiry(),
            by=self.admin,
        )
        self.log_in()
        response = self.upload(
            csv_file(
                "Identifiant;Mot de passe;Chambre;Résident;Valable jusqu'au",
                "vre8th;72ptmk;312;Lucas Petit;",  # 2: other name, warning only
                "vre8th;aaaaaa;999;;",  # 3: same username, unknown room
                "taken1;bbbbbb;305;;",  # 4: username of room 304, free room
                "newone;abc;305;;01/01/2020",  # 5: short password, past date
                "other1;cccccc;312;;",  # 6: same room as row 2
                "zzzzzz;dddddd;304;;demain",  # 7: unreadable date; replaces taken1
                ";;;;",  # empty: skipped
                "solo;;;;",  # 9: missing password and room
            )
        )
        rows = {row.number: row for row in response.context["rows"]}
        self.assertTrue(rows[2].ready)
        self.assertIn("Le fichier indique «\u00a0Lucas Petit\u00a0»", rows[2].warnings[0])
        self.assertEqual(
            rows[3].errors, ["Même identifiant que la ligne 2.", "La chambre 999 n'existe pas."]
        )
        self.assertEqual(rows[4].errors[0], "Cet identifiant sert déjà à la chambre 304.")
        self.assertIn("n'a pas de résident en ce moment", rows[4].errors[1])
        self.assertIn("Le mot de passe : il faut de 4 à 64 caractères.", rows[5].errors)
        self.assertIn("La date de fin doit être dans le futur.", rows[5].errors)
        self.assertIn("Même chambre que la ligne 2.", rows[6].errors)
        self.assertIn("«\u00a0demain\u00a0» n'est pas une date", rows[7].errors[0])
        self.assertIn("Remplace l'accès actuel (taken1).", rows[7].warnings)
        self.assertEqual(rows[9].errors, ["Le mot de passe manque.", "La chambre manque."])
        self.assertNotIn(8, rows)
        self.assertEqual(response.context["ready_count"], 1)
        self.confirm(response)
        self.assertEqual(WifiAccess.objects.filter(active=True).count(), 2)

    def test_replaces_the_current_access(self):
        old = wifi.set_access(
            self.r312,
            username="ancien",
            password="abcdef",
            expires_on=wifi.default_expiry(),
            by=self.admin,
        )
        self.log_in()
        response = self.upload(csv_file("Identifiant;Mot de passe;Chambre", "ancien;nouv01;312"))
        self.assertEqual(response.context["ready_count"], 1)  # same room: same username allowed
        self.confirm(response)
        old.refresh_from_db()
        self.assertFalse(old.active)
        new = wifi.current_access(self.r312)
        self.assertEqual(wifi_crypto.decrypt(new.encrypted_password), "nouv01")

    def test_missing_columns(self):
        self.log_in()
        response = self.upload(csv_file("Login;Chambre", "vre8th;312"))
        self.assertContains(response, "Il manque «\u00a0Mot de passe\u00a0».")
        self.assertNotIn("wifi_import", self.client.session)


class ConfirmationTests(WifiImportTestCase):
    def preview(self):
        self.log_in()
        return self.upload(csv_file("Identifiant;Mot de passe;Chambre", "vre8th;72ptmk;312"))

    def test_departure_after_the_preview(self):
        response = self.preview()
        record_departure(self.ines, timezone.localdate())
        response = self.confirm(response)
        self.assertContains(response, "La situation a changé depuis l'aperçu.")
        self.assertEqual(response.context["ready_count"], 0)
        self.assertFalse(WifiAccess.objects.exists())

    def test_access_recorded_after_the_preview(self):
        response = self.preview()
        wifi.set_access(
            self.r312,
            username="autre1",
            password="abcdef",
            expires_on=wifi.default_expiry(),
            by=self.admin,
        )
        response = self.confirm(response)
        self.assertContains(response, "La situation a changé depuis l'aperçu.")
        self.assertEqual(WifiAccess.objects.get().username, "autre1")

    def test_confirm_twice(self):
        response = self.preview()
        self.confirm(response)
        second = self.confirm(response)
        self.assertRedirects(second, reverse("residents:wifi_import"))
        self.assertEqual(WifiAccess.objects.count(), 1)

    def test_cancel(self):
        response = self.preview()
        response = self.client.post(
            reverse("residents:wifi_import_preview"),
            {"token": response.context["token"], "action": "cancel"},
            follow=True,
        )
        self.assertContains(response, "Aucun accès wifi n&#x27;a été enregistré.")
        self.assertFalse(WifiAccess.objects.exists())

    def test_expired_preview(self):
        self.preview()
        session = self.client.session
        session["wifi_import"]["created_at"] -= 31 * 60
        session.save()
        response = self.client.get(reverse("residents:wifi_import_preview"), follow=True)
        self.assertRedirects(response, reverse("residents:wifi_import"))
        self.assertContains(response, "L&#x27;aperçu a expiré.")


class ImportReviewTests(WifiImportTestCase):
    """Cases found by the independent review of T15b."""

    def test_two_columns_for_one_field(self):
        self.log_in()
        response = self.upload(
            csv_file("Chambre;Mot de passe;Identifiant;MDP", "312;72ptmk;vre8th;autre1")
        )
        self.assertContains(response, "Deux colonnes peuvent être «\u00a0Mot de passe\u00a0»")

    def test_door_code_and_person_columns_are_not_taken(self):
        self.log_in()
        response = self.upload(csv_file("Chambre;Utilisateur;Code", "312;Ines;4821"))
        self.assertContains(
            response, "Il manque «\u00a0Identifiant\u00a0» et «\u00a0Mot de passe\u00a0»."
        )
        response = self.upload(csv_file("Nom;Prénom", "Martin;Inès"))
        self.assertContains(
            response,
            "Il manque «\u00a0Identifiant\u00a0», «\u00a0Mot de passe\u00a0» "
            "et «\u00a0Chambre\u00a0».",
        )

    def test_scientific_text_from_a_saved_csv(self):
        self.log_in()
        response = self.upload(csv_file("Identifiant;Mot de passe;Chambre", "vre8th;2,34E+58;312"))
        self.assertEqual(response.context["ready_count"], 0)
        self.assertContains(response, "transformé en nombre par Excel")

    def test_other_format_is_a_warning(self):
        self.log_in()
        response = self.upload(
            csv_file("Identifiant;Mot de passe;Chambre", "ch312-ines;Soleil-2026!;312")
        )
        self.assertEqual(response.context["ready_count"], 1)
        self.assertContains(response, "L&#x27;identifiant ne suit pas le format du portail")
        self.assertContains(response, "Le mot de passe ne suit pas le format du portail")

    def test_same_list_again_changes_nothing(self):
        self.log_in()
        line = "vre8th;72ptmk;312"
        response = self.upload(csv_file("Identifiant;Mot de passe;Chambre", line))
        self.confirm(response)
        access = WifiAccess.objects.get()
        response = self.upload(
            csv_file("Identifiant;Mot de passe;Chambre", line, "k3pzqa;h7mwrd;304")
        )
        save_page("residents-wifi-import-unchanged", response)
        self.assertEqual(response.context["ready_count"], 1)
        self.assertEqual(response.context["unchanged_count"], 1)
        self.assertContains(response, "Déjà à jour")
        self.confirm(response)
        self.assertEqual(WifiAccess.objects.count(), 2)
        access.refresh_from_db()
        self.assertTrue(access.active)
        # A new password for the same username is a change.
        response = self.upload(csv_file("Identifiant;Mot de passe;Chambre", "vre8th;nouv01;312"))
        self.assertEqual(response.context["ready_count"], 1)

    def test_second_click_does_not_say_nothing_happened(self):
        from unittest import mock

        from django.core.exceptions import ValidationError

        self.log_in()
        response = self.upload(csv_file("Identifiant;Mot de passe;Chambre", "vre8th;72ptmk;312"))
        error = ValidationError(wifi.ACCESS_CHANGED, code="access_changed")
        with mock.patch("housing.wifi.set_access", side_effect=error):
            response = self.confirm(response)
        self.assertRedirects(response, reverse("residents:list"))
        self.assertContains(response, "peut-être par un premier clic")

    def test_front_desk_with_only_one_of_the_rights(self):
        self.log_in(self.front_desk)
        self.assertEqual(self.client.get(reverse("residents:wifi_import")).status_code, 403)


class SamePersonTests(TestCase):
    def test_marks_of_the_list_are_ignored(self):
        from residents.wifi_import import _same_person

        self.assertTrue(_same_person("Jean-Marc DUPONT*", "Jean-Marc Dupont"))
        self.assertTrue(_same_person(" jean-marc  dupont ", "Jean-Marc Dupont"))
        self.assertFalse(_same_person("Paul DUPONT", "Jean-Marc Dupont"))
