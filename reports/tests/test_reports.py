"""Report a problem (card T30)."""

import shutil
import tempfile
from datetime import date, timedelta
from io import BytesIO
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user
from housing.models import Floor, Room, Stay
from residence.models import ResidenceSettings
from tools.html_capture import save_page

from .. import photos
from ..models import Report, ReportEvent, ReportPhoto

NEW = reverse("reports:new")


def jpeg(size=(1200, 800), exif=True, name="photo.jpg"):
    """A JPEG as a phone sends it: GPS position, phone model, orientation 6."""
    image = Image.new("RGB", size, (200, 120, 40))
    out = BytesIO()
    if exif:
        data = Image.Exif()
        data[0x0112] = 6  # turned: to be shown rotated by 90 degrees
        data[0x0110] = "Phone X"
        data[0x8825] = {1: "N", 2: (47.0, 38.0, 10.0), 3: "E", 4: (6.0, 51.0, 30.0)}
        image.save(out, format="JPEG", exif=data.tobytes())
    else:
        image.save(out, format="JPEG")
    return SimpleUploadedFile(name, out.getvalue(), content_type="image/jpeg")


class ReportTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ines = make_user("ines", first_name="Inès", last_name="Martin")
        cls.yanis = make_user("yanis", first_name="Yanis")
        cls.nomad = make_user("nomad", first_name="Sans")  # no room
        cls.karim = make_user("karim", Role.FRONT_DESK, first_name="Karim")
        floor = Floor.objects.create(number=3)
        cls.room = Room.objects.create(number="312", floor=floor)
        Stay.objects.create(resident=cls.ines, room=cls.room, arrival=date(2026, 9, 1))
        Stay.objects.create(
            resident=cls.yanis,
            room=Room.objects.create(number="118", floor=floor),
            arrival=date(2026, 9, 1),
        )

    def setUp(self):
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        ResidenceSettings.objects.update_or_create(
            pk=1, defaults={"emergency_phone": "03 84 00 00 00"}
        )
        override = override_settings(MEDIA_ROOT=media)
        override.enable()
        self.addCleanup(override.disable)

    def data(self, **changes):
        return {
            "category": "electricity",
            "description": "La lampe de la salle de bain ne s'allume plus.",
            "urgency": "annoying",
            "access": "yes",
            **changes,
        }


class FormTests(ReportTestCase):
    def test_report_with_a_photo(self):
        log_in_verified(self.client, self.ines)
        response = self.client.get(NEW)
        save_page("reports-new", response)
        self.assertContains(response, "resident-page--task")
        self.assertContains(response, 'href="tel:0384000000"')
        self.assertContains(response, 'href="tel:112"')
        self.assertContains(response, "Chambre 312")
        before = timezone.now()
        response = self.client.post(NEW, self.data(photos=[jpeg()]))
        report = Report.objects.get()
        self.assertRedirects(
            response, reverse("reports:detail", args=[report.pk]), fetch_redirect_response=False
        )
        self.assertEqual((report.resident, report.room), (self.ines, self.room))
        self.assertTrue(report.access_allowed)
        self.assertEqual(report.status, Report.Status.NEW)
        self.assertLess(abs(report.due_at - (before + timedelta(hours=48))), timedelta(minutes=1))
        self.assertEqual(
            list(report.events.values_list("type", "author")),
            [(ReportEvent.Type.CREATED, self.ines.pk)],
        )
        # The photo: turned the right way, smaller, without any metadata.
        photo = report.photos.get()
        with photo.image.open("rb") as stored, Image.open(stored) as image:
            self.assertEqual(image.format, "JPEG")
            self.assertEqual(image.size, (800, 1200))
            self.assertEqual(dict(image.getexif()), {})
            self.assertNotIn("exif", image.info)
        self.assertNotIn("photo", photo.image.name)  # a random name
        response = self.client.get(reverse("reports:detail", args=[report.pk]))
        save_page("reports-detail", response)
        self.assertContains(response, "Signalement envoyé.")
        self.assertContains(response, 'alt="Photo 1" width="800" height="1200"')
        response = self.client.get(reverse("reports:photo", args=[photo.pk]))
        self.assertEqual(response["Content-Type"], "image/jpeg")
        self.assertIn("no-store", response["Cache-Control"])
        # The Signaler tab lists it.
        response = self.client.get(reverse("reports:list"))
        save_page("reports-list", response)
        self.assertContains(response, f'href="{reverse("reports:detail", args=[report.pk])}"')
        self.assertContains(response, 'aria-current="page">')

    def test_due_dates_by_urgency(self):
        log_in_verified(self.client, self.ines)
        for urgency, delay in (("urgent", timedelta(hours=4)), ("can_wait", timedelta(days=7))):
            self.client.post(NEW, self.data(urgency=urgency))
            report = Report.objects.latest("pk")
            self.assertEqual(report.due_at - report.created_at, delay)

    def test_missing_answers(self):
        log_in_verified(self.client, self.ines)
        response = self.client.post(NEW, {"description": " "})
        save_page("reports-new-errors", response)
        self.assertEqual(Report.objects.count(), 0)
        for text in (
            "Choisissez le type de problème.",
            "Dites en quelques mots ce qui ne va pas.",
            "Dites si c&#x27;est urgent.",
        ):
            self.assertContains(response, text)

    def test_photos_refused(self):
        log_in_verified(self.client, self.ines)
        response = self.client.post(
            NEW, self.data(photos=[jpeg(name=f"{i}.jpg") for i in range(4)])
        )
        self.assertContains(response, "3 photos au plus.")
        text = SimpleUploadedFile("note.jpg", b"not an image", content_type="image/jpeg")
        response = self.client.post(NEW, self.data(photos=[text]))
        self.assertContains(response, "pas une photo lisible")
        self.assertContains(response, "Ajoutez de nouveau vos photos.")
        self.assertEqual(Report.objects.count(), 0)
        self.assertEqual(ReportPhoto.objects.count(), 0)

    def test_too_many_pixels_refused_unread(self):
        out = BytesIO()
        Image.new("L", (6000, 6000)).save(out, format="PNG")  # 36 megapixels, small file
        with self.assertRaisesMessage(photos.PhotoRefused, "trop grande"):
            photos.clean(SimpleUploadedFile("big.png", out.getvalue()))

    def test_transparent_png_on_white(self):
        out = BytesIO()
        Image.new("RGBA", (40, 20), (0, 0, 0, 0)).save(out, format="PNG")
        content, _, _ = photos.clean(SimpleUploadedFile("t.png", out.getvalue()))
        with Image.open(BytesIO(content.read())) as image:
            self.assertEqual((image.mode, image.getpixel((0, 0))), ("RGB", (255, 255, 255)))

    def test_without_a_room(self):
        log_in_verified(self.client, self.nomad)
        response = self.client.get(NEW)
        self.assertContains(response, "Aucune chambre n'est liée à votre compte.")
        self.client.post(NEW, self.data())
        self.assertEqual(Report.objects.count(), 0)

    def test_staff_is_sent_home(self):
        log_in_verified(self.client, self.karim)
        self.assertRedirects(self.client.get(NEW), reverse("home"), fetch_redirect_response=False)


class PrivacyTests(ReportTestCase):
    def test_only_my_reports_and_photos(self):
        log_in_verified(self.client, self.ines)
        self.client.post(NEW, self.data(photos=[jpeg(exif=False)]))
        report = Report.objects.get()
        photo = report.photos.get()
        log_in_verified(self.client, self.yanis)
        self.assertEqual(
            self.client.get(reverse("reports:detail", args=[report.pk])).status_code, 404
        )
        self.assertEqual(
            self.client.get(reverse("reports:photo", args=[photo.pk])).status_code, 404
        )
        self.assertNotContains(self.client.get(reverse("reports:list")), "Électricité")

    def test_photo_files_go_with_the_report(self):
        log_in_verified(self.client, self.ines)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(NEW, self.data(photos=[jpeg(exif=False)]))
        photo = ReportPhoto.objects.get()
        storage, name = photo.image.storage, photo.image.name
        self.assertTrue(storage.exists(name))
        with self.captureOnCommitCallbacks(execute=True):
            Report.objects.all().delete()
        self.assertFalse(storage.exists(name))

    def test_no_emergency_number_set(self):
        log_in_verified(self.client, self.ines)
        ResidenceSettings.objects.filter(pk=1).update(emergency_phone="")
        response = self.client.get(NEW)
        self.assertContains(response, "Appelez tout de suite l'accueil.")


class ReviewTests(ReportTestCase):
    """Independent review of T30."""

    def test_jpeg_comment_removed(self):
        out = BytesIO()
        Image.new("RGB", (50, 50)).save(out, format="JPEG", comment=b"<script>x</script>")
        content, _, _ = photos.clean(SimpleUploadedFile("c.jpg", out.getvalue()))
        data = content.read()
        self.assertNotIn(b"script", data)
        with Image.open(BytesIO(data)) as image:
            self.assertNotIn("comment", image.info)

    def test_other_formats_and_heavy_files_refused(self):
        for fmt in ("GIF", "TIFF"):
            out = BytesIO()
            Image.new("RGB", (20, 20)).save(out, format=fmt)
            with self.assertRaises(photos.PhotoRefused):
                photos.clean(SimpleUploadedFile(f"x.{fmt.lower()}", out.getvalue()))
        heavy = SimpleUploadedFile("big.jpg", b"0" * (photos.MAX_BYTES + 1))
        with self.assertRaisesMessage(photos.PhotoRefused, "10 Mo"):
            photos.clean(heavy)

    def test_failure_leaves_no_file(self):
        log_in_verified(self.client, self.ines)
        storage = ReportPhoto.image.field.storage
        with (
            mock.patch("reports.service.ReportEvent.objects.create", side_effect=RuntimeError),
            self.assertRaises(RuntimeError),
        ):
            self.client.post(NEW, self.data(photos=[jpeg(exif=False)]))
        self.assertEqual(Report.objects.count(), 0)
        _, files = storage.listdir("reports") if storage.exists("reports") else ([], [])
        self.assertEqual(files, [])

    def test_access_no_and_values_kept_after_an_error(self):
        log_in_verified(self.client, self.ines)
        response = self.client.post(NEW, self.data(urgency="", access="no"))
        self.assertContains(response, "Vérifiez les points en rouge.")
        self.assertContains(response, 'value="electricity" required checked')
        self.assertContains(response, 'value="no" required checked')
        self.assertContains(response, "ne s&#x27;allume plus")
        self.client.post(NEW, self.data(access="no"))
        self.assertFalse(Report.objects.get().access_allowed)

    def test_anonymous_and_staff(self):
        log_in_verified(self.client, self.ines)
        self.client.post(NEW, self.data(photos=[jpeg(exif=False)]))
        report = Report.objects.get()
        urls = [
            reverse("reports:list"),
            reverse("reports:detail", args=[report.pk]),
            reverse("reports:photo", args=[report.photos.get().pk]),
        ]
        self.client.logout()
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 302)
        log_in_verified(self.client, self.karim)
        self.assertEqual(self.client.get(urls[0]).status_code, 302)
        for url in urls[1:]:
            self.assertEqual(self.client.get(url).status_code, 404)
