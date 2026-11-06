"""CSV and Excel import. All the data is made up."""

import io
import zipfile
from datetime import date, datetime

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook

from accounts.models import User
from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user
from housing.models import Floor, Room, Stay
from housing.services import current_stay
from residents.bulk_import import (
    MAX_ROWS,
    MAX_SIZE,
    MAX_UNCOMPRESSED_SIZE,
    FileError,
    ImportRow,
    analyze,
    read_file,
    run_import,
)
from residents.models import ResidentImport
from tools.html_capture import save_page

TODAY = date(2026, 11, 5)


def csv_(text, name="residents.csv", encoding="utf-8-sig"):
    return SimpleUploadedFile(name, text.encode(encoding), content_type="text/csv")


def xlsx(rows, name="residents.xlsx"):
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return SimpleUploadedFile(name, buffer.getvalue())


class ImportTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.f3 = Floor.objects.create(number=3)
        cls.r304 = Room.objects.create(number="304", floor=cls.f3)
        cls.r305 = Room.objects.create(number="305", floor=cls.f3)
        cls.r312 = Room.objects.create(number="312", floor=cls.f3)
        cls.closed = Room.objects.create(number="399", floor=cls.f3, active=False)
        cls.awa = make_user("awa.kone", first_name="Awa", last_name="Koné", phone="+33612345647")
        Stay.objects.create(resident=cls.awa, room=cls.r312, arrival=date(2026, 9, 1))


class ReadingTests(ImportTestCase):
    def test_csv_semicolon_with_bom(self):
        rows = read_file(csv_("Prénom;Nom;Chambre\nInès;Martin;304\n"))
        self.assertEqual(rows, [(1, ["Prénom", "Nom", "Chambre"]), (2, ["Inès", "Martin", "304"])])

    def test_csv_comma_and_quotes(self):
        rows = read_file(csv_('Prénom,Nom\n"Jean, dit Jo",Durand\n'))
        self.assertEqual(rows[1][1], ["Jean, dit Jo", "Durand"])

    def test_csv_windows_1252(self):
        rows = read_file(csv_("Prénom;Nom\nLéa;Moreau\n", encoding="cp1252"))
        self.assertEqual(rows[1][1], ["Léa", "Moreau"])

    def test_empty_rows_ignored(self):
        rows = read_file(csv_("Prénom;Nom\n;\nLéa;Moreau\n\n"))
        # The empty row disappears, but Léa keeps her row number: 3.
        self.assertEqual(rows, [(1, ["Prénom", "Nom"]), (3, ["Léa", "Moreau"])])

    def test_xlsx(self):
        file = xlsx(
            [
                ["Prénom", "Nom", "Téléphone", "Arrivée"],
                ["Léa", "Moreau", 612345678, datetime(2026, 9, 1)],
            ]
        )
        rows = read_file(file)
        self.assertEqual(rows[1], (2, ["Léa", "Moreau", 612345678, datetime(2026, 9, 1)]))

    def test_refused_files(self):
        cases = {
            "old format": (SimpleUploadedFile("a.xls", b"x"), "(.xls)"),
            "extension": (SimpleUploadedFile("a.pdf", b"x"), ".csv ou un .xlsx"),
            "empty": (csv_("\n\n"), "vide"),
            "unreadable": (SimpleUploadedFile("a.xlsx", b"pas un classeur"), "illisible"),
            "too long": (csv_("Prénom;Nom\n" + "A;B\n" * (MAX_ROWS + 1)), "500 lignes"),
        }
        for name, (file, excerpt) in cases.items():
            with self.subTest(name), self.assertRaisesMessage(FileError, excerpt):
                read_file(file)

    def test_too_heavy(self):
        file = csv_("Prénom;Nom\n")
        file.size = 3 * 1024 * 1024
        with self.assertRaisesMessage(FileError, "2 Mo"):
            read_file(file)


class AnalysisTests(ImportTestCase):
    def analyze(self, *rows, header=("Prénom", "Nom", "Téléphone", "Chambre", "Arrivée", "E-mail")):
        return analyze(list(enumerate([list(header), *map(list, rows)], start=1)))

    def errors(self, *rows, **kwargs):
        return [row.errors for row in self.analyze(*rows, **kwargs)]

    def test_ready_row(self):
        (row,) = self.analyze(("Inès", "Martin", "07 81 23 45 88", "304", "03/11/2026", ""))
        self.assertTrue(row.ready)
        self.assertEqual(row.number, 2)
        self.assertEqual(row.phone, "+33781234588")
        self.assertEqual(row.phone_display, "07 81 23 45 88")
        self.assertEqual(row.arrival_date, date(2026, 11, 3))

    def test_flexible_headers_and_columns_in_any_order(self):
        (row,) = self.analyze(("304", "martin", "Inès"), header=(" N° chambre ", "NOM", "prenom"))
        self.assertEqual((row.first_name, row.last_name, row.room), ("Inès", "martin", "304"))
        # Room without a date: arrival on the import day, computed at that moment.
        self.assertTrue(row.auto_arrival)
        self.assertEqual(row.arrival_date, timezone.localdate())

    def test_required_headers(self):
        with self.assertRaisesMessage(FileError, "Il manque « Prenom » et « Nom »"):
            analyze([(1, ["Téléphone"]), (2, ["06 12 34 56 78"])])

    def test_values_coming_from_excel(self):
        (row,) = self.analyze(("Léa", "Moreau", 612345678, 304.0, datetime(2026, 9, 1), ""))
        self.assertTrue(row.ready, row.errors)
        self.assertEqual(row.phone, "+33612345678")
        self.assertEqual(row.room, "304")

    def test_errors_explained(self):
        cases = [
            (("", "", "", "", "", ""), ["Le prénom manque.", "Le nom manque."]),
            (
                ("A", "B", "06 12 34", "", "", ""),
                ["Numéro « 06 12 34 » : Ce numéro n'existe pas. Vérifiez les chiffres."],
            ),
            (("A", "B", "06 12 34 56 47", "", "", ""), ["Ce numéro est déjà celui de Awa Koné."]),
            (("A", "B", "", "999", "", ""), ["La chambre 999 n'existe pas."]),
            (("A", "B", "", "399", "", ""), ["La chambre 399 est fermée."]),
            (("A", "B", "", "312", "", ""), ["La chambre 312 est déjà occupée par Awa Koné."]),
            (
                ("A", "B", "", "304", "31/02/2026", ""),
                ["« 31/02/2026 » n'est pas une date. Écrivez-la comme 01/09/2026."],
            ),
            (("A", "B", "", "", "", "a@"), ["« a@ » n'est pas une adresse e-mail."]),
        ]
        for row, expected in cases:
            with self.subTest(row=row):
                self.assertEqual(self.errors(row), [expected])

    def test_duplicates_in_the_file(self):
        errors = self.errors(
            ("A", "B", "07 81 23 45 88", "304", "", ""),
            ("C", "D", "+33 7 81 23 45 88", "304", "", ""),
        )
        self.assertEqual(errors[0], [])
        self.assertEqual(errors[1], ["Même numéro que la ligne 2.", "Même chambre que la ligne 2."])

    def test_same_name_flagged_without_blocking(self):
        (row,) = self.analyze(("awa", "KONÉ", "", "", "", ""))
        self.assertTrue(row.ready)
        self.assertIn("Une fiche existe déjà à ce nom", row.warnings[0])

    def test_query_count_independent_of_the_row_count(self):
        rows = [(f"P{i}", f"N{i}", f"07 81 23 45 {i:02}", "304", "", "") for i in range(40)]
        with self.assertNumQueries(4):
            self.analyze(*rows)


class RunImportTests(ImportTestCase):
    def test_all_or_nothing(self):
        good = ImportRow(
            number=2, first_name="Inès", last_name="Martin", room="304", arrival="2026-11-03"
        )
        # Row that looks ready but targets a taken room: refused at the last moment.
        trap = ImportRow(
            number=3, first_name="Léa", last_name="Moreau", room="312", arrival="2026-11-03"
        )
        before = User.objects.count()
        with self.assertRaises(ValidationError):
            run_import([good, trap])
        self.assertEqual(User.objects.count(), before)
        self.assertFalse(Stay.objects.filter(room=self.r304).exists())


class ImportPagesTests(ImportTestCase):
    def setUp(self):
        log_in_verified(self.client, make_user("nadia", Role.FRONT_DESK))

    def upload(self, file):
        return self.client.post(reverse("residents:import"), {"file": file})

    def confirm(self, ready, token=None, action="import", **kwargs):
        token = token or self.client.session["resident_import"]["token"]
        return self.client.post(
            reverse("residents:import_preview"),
            {"action": action, "ready": ready, "token": token},
            **kwargs,
        )

    def sample_file(self):
        return csv_(
            "Prénom;Nom;Téléphone;Chambre;Arrivée\n"
            "Inès;Martin;07 81 23 45 88;304;03/11/2026\n"
            "Léa;Moreau;06 12 34;;\n"
            "Moussa;Diallo;;305;01/11/2026\n"
            "Zoé;Bernard;06 12 34 56 47;;\n"
        )

    def test_only_for_resident_managers(self):
        log_in_verified(self.client, make_user("sam", Role.EDUCATOR))
        for name in ["import", "import_preview", "import_template"]:
            self.assertEqual(self.client.get(reverse(f"residents:{name}")).status_code, 403)

    def test_upload_page(self):
        response = self.client.get(reverse("residents:import"))
        save_page("residents-import", response)
        self.assertContains(response, 'enctype="multipart/form-data"')
        self.assertContains(response, 'accept=".csv,.xlsx"')
        response = self.client.get(reverse("residents:list"))
        self.assertContains(response, "Des résidents (CSV ou Excel)")

    def test_file_refused(self):
        response = self.upload(SimpleUploadedFile("vieux.xls", b"x"))
        save_page("residents-import-error", response)
        self.assertContains(response, "L&#x27;ancien format Excel (.xls)")
        self.assertContains(response, 'aria-invalid="true"')

    def test_preview_then_import(self):
        response = self.upload(self.sample_file())
        self.assertRedirects(response, reverse("residents:import_preview"))
        response = self.client.get(reverse("residents:import_preview"))
        save_page("residents-import-preview", response)
        self.assertContains(response, "Aperçu · residents.csv")
        self.assertContains(response, "2 prêtes")
        self.assertContains(response, "2 à corriger")
        self.assertContains(response, "Ce numéro est déjà celui de Awa Koné.")
        self.assertContains(response, 'name="ready" value="2,4"')
        self.assertContains(response, "Importer les 2 lignes prêtes")

        response = self.confirm("2,4", follow=True)
        self.assertRedirects(response, reverse("residents:list"))
        self.assertContains(response, "2 résidents importés.")
        ines = User.objects.get(first_name="Inès")
        self.assertEqual(ines.phone, "+33781234588")
        self.assertFalse(ines.has_usable_password())
        self.assertEqual(current_stay(ines).arrival, date(2026, 11, 3))
        moussa = User.objects.get(first_name="Moussa")
        self.assertEqual(current_stay(moussa).room, self.r305)
        self.assertFalse(User.objects.filter(first_name__in=["Léa", "Zoé"]).exists())
        self.assertNotIn("resident_import", self.client.session)

    def test_state_changed_before_the_confirmation(self):
        self.upload(self.sample_file())
        # Between the preview and the confirmation, someone houses another person in 304.
        Stay.objects.create(resident=make_user("x"), room=self.r304, arrival=TODAY)
        response = self.confirm("2,4")
        self.assertContains(response, "La situation a changé depuis l'aperçu.")
        self.assertContains(response, 'name="ready" value="4"')
        self.assertFalse(User.objects.filter(first_name="Inès").exists())

    def test_cancel(self):
        self.upload(self.sample_file())
        response = self.confirm("", action="cancel", follow=True)
        self.assertRedirects(response, reverse("residents:import"))
        self.assertContains(response, "Import annulé. Aucune fiche n&#x27;a été créée.")
        self.assertFalse(User.objects.filter(first_name="Inès").exists())

    def test_preview_without_file(self):
        response = self.client.get(reverse("residents:import_preview"))
        self.assertRedirects(response, reverse("residents:import"))

    def test_xlsx_end_to_end(self):
        self.upload(
            xlsx([["Nom", "Prénom", "Portable", "Chambre"], ["Diallo", "Moussa", 781234588, 305]])
        )
        self.confirm("2")
        moussa = User.objects.get(first_name="Moussa")
        self.assertEqual(moussa.phone, "+33781234588")
        self.assertEqual(current_stay(moussa).room, self.r305)

    def test_csv_template(self):
        response = self.client.get(reverse("residents:import_template"))
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("attachment", response["Content-Disposition"])
        text = response.content.decode("utf-8-sig")
        self.assertEqual(text, "Prénom;Nom;Téléphone;Chambre;Arrivée;E-mail\r\n")
        # The template can be read back without error.
        rows = read_file(SimpleUploadedFile("modele.csv", response.content))
        self.assertEqual(len(rows), 1)


class TrappedFilesTests(ImportTestCase):
    """Damaged or trapped files: refused with a message, never a 500 error."""

    def test_empty_rows_do_not_lose_rows(self):
        rows = "".join(f"P{i};N{i}\n" for i in range(MAX_ROWS))
        file = csv_("Prénom;Nom\n\n\n" + rows + "\n\n")
        self.assertEqual(len(read_file(file)), MAX_ROWS + 1)
        with self.assertRaisesMessage(FileError, "500 lignes"):
            read_file(csv_("Prénom;Nom\n\n" + rows + "Un;De trop\n"))

    def test_too_many_empty_rows(self):
        with self.assertRaisesMessage(FileError, "500 lignes"):
            read_file(csv_("Prénom;Nom\n" + ";\n" * 6000))

    def test_unreadable_csv(self):
        cases = {
            "encoding": (SimpleUploadedFile("a.csv", b"Pr\x81nom;Nom\n"), "illisibles"),
            "huge cell": (csv_('Prénom;Nom\n"' + "x" * 200_000 + '";B\n'), "mal formé"),
        }
        for name, (file, excerpt) in cases.items():
            with self.subTest(name), self.assertRaisesMessage(FileError, excerpt):
                read_file(file)

    def _modified_xlsx(self, modify):
        source = xlsx([["Prénom", "Nom"], ["Léa", "Moreau"]])
        source_buffer, output = io.BytesIO(source.read()), io.BytesIO()
        with (
            zipfile.ZipFile(source_buffer) as zin,
            zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zout,
        ):
            for info in zin.infolist():
                zout.writestr(info, modify(info.filename, zin.read(info.filename)))
            if modify("extra", None) is not None:
                zout.writestr("extra.bin", modify("extra", None))
        return SimpleUploadedFile("a.xlsx", output.getvalue())

    def test_damaged_xlsx_xml(self):
        file = self._modified_xlsx(
            lambda name, content: content[:-40] if name.endswith("sheet1.xml") else content
        )
        with self.assertRaisesMessage(FileError, "illisible"):
            read_file(file)

    def test_inflating_xlsx(self):
        big = b"0" * (MAX_UNCOMPRESSED_SIZE + 1)
        file = self._modified_xlsx(lambda name, content: big if name == "extra" else content)
        self.assertLess(file.size, MAX_SIZE)
        with self.assertRaisesMessage(FileError, "illisible"):
            read_file(file)


class EndedStayTests(ImportTestCase):
    def test_arrival_during_a_past_stay(self):
        Stay.objects.create(
            resident=make_user("former"),
            room=self.r305,
            arrival=date(2025, 9, 1),
            departure=date(2026, 6, 30),
        )
        rows = analyze(
            [(1, ["Prénom", "Nom", "Chambre", "Arrivée"]), (2, ["A", "B", "305", "01/03/2026"])]
        )
        self.assertEqual(
            rows[0].errors,
            [
                "La chambre 305 était occupée jusqu'au 30/06/2026 : "
                "l'arrivée doit être à partir de cette date."
            ],
        )

    def test_import_error_gives_the_row(self):
        trap = ImportRow(
            number=7, first_name="Léa", last_name="Moreau", room="312", arrival="2026-11-03"
        )
        with self.assertRaisesMessage(ValidationError, "Ligne 7 :"):
            run_import([trap])


class ConfirmationTests(ImportPagesTests):
    def file(self, name, first_name):
        return csv_(f"Prénom;Nom\n{first_name};Test\n", name=name)

    def test_two_tabs(self):
        self.upload(self.file("a.csv", "Alice"))
        token_a = self.client.session["resident_import"]["token"]
        self.upload(self.file("b.csv", "Bruno"))
        response = self.confirm("2", token=token_a)
        self.assertContains(response, "Un autre fichier a été envoyé depuis.")
        self.assertContains(response, "Aperçu · b.csv")
        self.assertFalse(User.objects.filter(last_name="Test").exists())

    def test_double_submit(self):
        self.upload(self.file("a.csv", "Alice"))
        data = self.client.session["resident_import"]
        self.confirm("2")
        # Second request sent before the first one emptied the session.
        session = self.client.session
        session["resident_import"] = data
        session.save()
        response = self.confirm("2", follow=True)
        self.assertContains(response, "Cet import a déjà été fait.")
        self.assertEqual(User.objects.filter(first_name="Alice").count(), 1)
        record = ResidentImport.objects.get()
        self.assertEqual((record.file_name, record.count), ("a.csv", 1))

    def test_preview_expired(self):
        self.upload(self.file("a.csv", "Alice"))
        session = self.client.session
        session["resident_import"]["created_at"] -= 2 * 60 * 60
        session.save()
        response = self.client.get(reverse("residents:import_preview"), follow=True)
        self.assertRedirects(response, reverse("residents:import"))
        self.assertContains(response, "L&#x27;aperçu a expiré.")
        self.assertNotIn("resident_import", self.client.session)

    def test_arrival_on_the_import_day(self):
        self.upload(csv_("Prénom;Nom;Chambre\nAlice;Test;304\n"))
        response = self.client.get(reverse("residents:import_preview"))
        self.assertContains(response, "Aujourd'hui")
        self.confirm("2")
        alice = User.objects.get(first_name="Alice")
        self.assertEqual(current_stay(alice).arrival, timezone.localdate())
