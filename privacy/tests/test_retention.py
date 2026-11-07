"""Retention durations, the purge and the page "Vos données" (card T36)."""

import shutil
import tempfile
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import ActivationFailure, User
from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user
from appointments.models import Appointment, Conversation, DirectMessage
from audit.models import Action, AuditEntry
from housing.models import Floor, Room, Stay
from messaging.models import AttendanceReply, Campaign, Delivery
from push.models import PushSubscription
from reports.models import Report, ReportEvent, ReportPhoto
from tools.html_capture import save_page

from .. import retention

PAGE = reverse("privacy")


class RetentionTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.now = timezone.now()
        today = timezone.localdate()
        floor = Floor.objects.create(number=2)
        cls.room = Room.objects.create(number="201", floor=floor)
        cls.samia = make_user("samia", Role.EDUCATOR, first_name="Samia")
        cls.karim = make_user("karim", Role.FRONT_DESK, first_name="Karim")
        # Gone 400 days ago: to delete.
        cls.old = make_user("old", first_name="Ancien", is_active=False)
        Stay.objects.create(
            resident=cls.old,
            room=cls.room,
            arrival=today - timedelta(days=800),
            departure=today - timedelta(days=400),
        )
        # Gone 100 days ago: kept.
        cls.recent = make_user("recent", first_name="Récent", is_active=False)
        Stay.objects.create(
            resident=cls.recent,
            room=Room.objects.create(number="202", floor=floor),
            arrival=today - timedelta(days=500),
            departure=today - timedelta(days=100),
        )
        # Housed, account cut (lost phone): kept, whatever the dates.
        cls.housed = make_user("housed", is_active=False)
        Stay.objects.create(
            resident=cls.housed,
            room=Room.objects.create(number="203", floor=floor),
            arrival=today - timedelta(days=900),
        )
        # A staff account switched off long ago: never touched.
        cls.former_staff = make_user("former_staff", Role.MAINTENANCE, is_active=False)
        User.objects.filter(pk=cls.former_staff.pk).update(
            date_joined=cls.now - timedelta(days=900)
        )

    def setUp(self):
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=media)
        override.enable()
        self.addCleanup(override.disable)

    def report(self, resident, status=Report.Status.NEW, days_ago=0):
        report = Report.objects.create(
            resident=resident,
            room=self.room,
            category="heating",
            description="Radiateur froid",
            urgency="annoying",
            due_at=self.now,
            status=status,
        )
        photo = ReportPhoto(report=report, width=10, height=10)
        photo.image.save("x.jpg", ContentFile(b"jpeg"), save=True)
        Report.objects.filter(pk=report.pk).update(updated_at=self.now - timedelta(days=days_ago))
        return report, photo

    def old_audit(self, days_ago):
        return AuditEntry.objects.create(
            action=Action.WIFI_PASSWORD_SHOWN,
            created_at=self.now - timedelta(days=days_ago),
            details={"room": "201"},
        )


class PurgeTests(RetentionTestCase):
    def test_former_residents(self):
        found = set(retention.former_residents(self.now))
        self.assertEqual(found, {self.old})

    def test_dry_run_deletes_nothing(self):
        self.old_audit(400)
        result = retention.run(now=self.now)
        self.assertEqual(result.former_residents, 1)
        self.assertEqual(result.audit_entries, 1)
        self.assertTrue(User.objects.filter(pk=self.old.pk).exists())
        self.assertEqual(AuditEntry.objects.count(), 1)

    def test_former_resident_goes_with_all_their_data(self):
        report, photo = self.report(self.old)
        ReportEvent.objects.create(
            report=report, author=self.old, type="reopened", note="Mon nom est Ancien"
        )
        storage, name = photo.image.storage, photo.image.name
        self.assertEqual(retention.run(now=self.now).report_photos, 1)  # the dry run
        start = self.now - timedelta(days=30)
        Appointment.objects.create(
            educator=self.samia, resident=self.old, start=start, end=start + timedelta(hours=1)
        )
        PushSubscription.objects.create(
            user=self.old, endpoint="https://web.push.apple.com/x", p256dh="x", auth="y"
        )
        with self.captureOnCommitCallbacks(execute=True):
            result = retention.run(apply=True, now=self.now)
        self.assertEqual(result.former_residents, 1)
        self.assertFalse(User.objects.filter(pk=self.old.pk).exists())
        self.assertFalse(Stay.objects.filter(resident_id=self.old.pk).exists())
        # The report stays, without the person and without its photos.
        report.refresh_from_db()
        self.assertIsNone(report.resident)
        self.assertFalse(report.photos.exists())
        self.assertEqual(report.description, "")
        self.assertEqual(report.status, Report.Status.CLOSED)  # nobody can confirm it
        self.assertFalse(report.events.exclude(note="").exists())
        self.assertTrue(report.events.filter(type="closed").exists())
        self.assertEqual(result.report_photos, 1)
        log_in_verified(self.client, self.karim)
        response = self.client.get(reverse("reports_staff:detail", args=[report.pk]))
        save_page("reports-staff-detail-former", response)
        self.assertContains(response, "Ancien résident, compte supprimé")
        self.assertContains(response, "Texte retiré avec le compte du résident.")
        self.assertNotContains(response, "Mon nom est Ancien")
        self.assertNotContains(response, "Ancien</a>")
        self.assertFalse(Appointment.objects.filter(resident_id=self.old.pk).exists())
        self.assertFalse(PushSubscription.objects.exists())
        self.assertFalse(storage.exists(name))
        # The others stay; the educator and the room too.
        for kept in (self.recent, self.housed, self.former_staff, self.samia):
            self.assertTrue(User.objects.filter(pk=kept.pk).exists())
        self.assertTrue(Room.objects.filter(pk=self.room.pk).exists())

    def test_someone_back_meanwhile_is_kept(self):
        from residents.departure import record_return

        real = retention._lock_former

        def back_first(candidates):
            # Came back between the count and the deletion.
            room = Room.objects.create(number="205", floor=self.room.floor)
            record_return(self.old, room, timezone.localdate())
            return real(candidates)

        with mock.patch.object(retention, "_lock_former", side_effect=back_first):
            result = retention.run(apply=True, now=self.now)
        self.assertEqual(result.former_residents, 0)
        self.assertTrue(User.objects.filter(pk=self.old.pk).exists())
        self.assertFalse(AuditEntry.objects.filter(action=Action.DATA_PURGED).exists())

    def test_account_without_any_stay_is_never_chosen(self):
        # An educator whose roles were removed, account switched off long ago.
        gone = make_user("gone_educator", is_active=False)
        User.objects.filter(pk=gone.pk).update(date_joined=self.now - timedelta(days=900))
        talk = Conversation.objects.create(resident=self.housed, educator=gone)
        DirectMessage.objects.create(conversation=talk, author=gone, text="Bonjour")
        self.assertNotIn(gone, retention.former_residents(self.now))
        retention.run(apply=True, now=self.now)
        self.assertTrue(User.objects.filter(pk=gone.pk).exists())
        self.assertTrue(DirectMessage.objects.filter(conversation=talk).exists())

    def test_a_protected_account_stays_and_the_rest_goes_on(self):
        # Still the educator of a recent meeting: PROTECT.
        start = self.now - timedelta(days=5)
        Appointment.objects.create(
            educator=self.old, resident=self.recent, start=start, end=start + timedelta(hours=1)
        )
        self.old_audit(400)
        result = retention.run(apply=True, now=self.now)
        self.assertEqual(result.former_residents, 0)
        self.assertEqual(result.audit_entries, 1)
        self.assertTrue(User.objects.filter(pk=self.old.pk).exists())
        purge = AuditEntry.objects.get(action=Action.DATA_PURGED)
        self.assertEqual(purge.details, {"audit_entries": 1, "kept": 1})
        self.assertIn("1 ancien compte gardé, encore lié", purge.summary())

    def test_names_in_messages_and_empty_conversations(self):
        old = self.now - timedelta(days=400)
        campaign = Campaign.objects.create(
            title="Visite", body="B", author=self.karim, status=Campaign.Status.SENT, started_at=old
        )
        campaign.people.add(self.recent)
        campaign.excluded.add(self.housed)
        recent = Campaign.objects.create(
            title="Fête",
            body="B",
            author=self.karim,
            status=Campaign.Status.SENT,
            started_at=self.now,
        )
        recent.people.add(self.recent)
        empty = Conversation.objects.create(resident=self.recent, educator=self.samia)
        Conversation.objects.filter(pk=empty.pk).update(updated_at=old)
        alive = Conversation.objects.create(resident=self.housed, educator=self.samia)
        Conversation.objects.filter(pk=alive.pk).update(updated_at=old)
        DirectMessage.objects.create(conversation=alive, author=self.housed, text="Encore là")
        result = retention.run(apply=True, now=self.now)
        self.assertEqual(result.conversations, 1)
        self.assertFalse(Conversation.objects.filter(pk=empty.pk).exists())
        self.assertTrue(Conversation.objects.filter(pk=alive.pk).exists())
        self.assertFalse(campaign.people.exists())
        self.assertFalse(campaign.excluded.exists())
        self.assertTrue(recent.people.exists())

    def test_wifi_accesses(self):
        from housing.models import WifiAccess

        today = timezone.localdate()

        def access(name, **fields):
            return WifiAccess.objects.create(
                room=self.room,
                username=name,
                encrypted_password="x",
                created_on=today - timedelta(days=800),
                expires_on=today - timedelta(days=400),
                **fields,
            )

        ended = access("a", active=False, ended_at=self.now - timedelta(days=400))
        no_end = access("b", active=False)
        recent = access("c", active=False, ended_at=self.now - timedelta(days=10))
        retention.run(apply=True, now=self.now)
        self.assertFalse(WifiAccess.objects.filter(pk__in=[ended.pk, no_end.pk]).exists())
        self.assertTrue(WifiAccess.objects.filter(pk=recent.pk).exists())

    def test_photos_of_closed_reports(self):
        _, old_photo = self.report(self.recent, Report.Status.CLOSED, days_ago=200)
        _, recent_photo = self.report(self.recent, Report.Status.CLOSED, days_ago=20)
        _, open_photo = self.report(self.recent, Report.Status.DONE, days_ago=400)
        with self.captureOnCommitCallbacks(execute=True):
            result = retention.run(apply=True, now=self.now)
        self.assertEqual(result.report_photos, 1)
        self.assertFalse(ReportPhoto.objects.filter(pk=old_photo.pk).exists())
        self.assertFalse(old_photo.image.storage.exists(old_photo.image.name))
        self.assertTrue(ReportPhoto.objects.filter(pk=recent_photo.pk).exists())
        self.assertTrue(ReportPhoto.objects.filter(pk=open_photo.pk).exists())
        self.assertEqual(Report.objects.count(), 3)  # the reports stay

    def test_meetings_messages_and_deliveries(self):
        old_start = self.now - timedelta(days=400)
        old = Appointment.objects.create(
            educator=self.samia,
            resident=self.recent,
            start=old_start,
            end=old_start + timedelta(hours=1),
            reason=Appointment.Reason.BUDGET,
        )
        start = self.now - timedelta(days=10)
        kept = Appointment.objects.create(
            educator=self.samia, resident=self.recent, start=start, end=start + timedelta(hours=1)
        )
        talk = Conversation.objects.create(resident=self.recent, educator=self.samia)
        message = DirectMessage.objects.create(conversation=talk, author=self.recent, text="Hi")
        DirectMessage.objects.filter(pk=message.pk).update(sent_at=self.now - timedelta(days=400))
        DirectMessage.objects.create(conversation=talk, author=self.samia, text="Hello")
        campaign = Campaign.objects.create(
            title="Visite",
            body="B",
            author=self.karim,
            status=Campaign.Status.SENT,
            started_at=self.now - timedelta(days=400),
        )
        Delivery.objects.create(
            campaign=campaign, recipient=self.recent, channel="push", title="T", body="B"
        )
        AttendanceReply.objects.create(campaign=campaign, resident=self.recent, answer="present")
        retention.run(apply=True, now=self.now)
        self.assertFalse(Appointment.objects.filter(pk=old.pk).exists())
        self.assertTrue(Appointment.objects.filter(pk=kept.pk).exists())
        self.assertEqual(list(DirectMessage.objects.values_list("text", flat=True)), ["Hello"])
        self.assertFalse(Delivery.objects.exists())
        self.assertFalse(AttendanceReply.objects.exists())
        self.assertTrue(Campaign.objects.filter(pk=campaign.pk).exists())

    def test_audit_log_and_codes(self):
        self.old_audit(400)
        recent = self.old_audit(10)
        failure = ActivationFailure.objects.create(ip_address="192.0.2.1")
        ActivationFailure.objects.filter(pk=failure.pk).update(
            created_at=self.now - timedelta(days=40)
        )
        ActivationFailure.objects.create(ip_address="192.0.2.2")
        retention.run(apply=True, now=self.now)
        self.assertEqual(ActivationFailure.objects.count(), 1)
        entries = list(AuditEntry.objects.order_by("created_at"))
        self.assertEqual(entries[0], recent)
        purge = entries[-1]
        self.assertEqual(purge.action, Action.DATA_PURGED)
        self.assertEqual(purge.details, {"former_residents": 1, "audit_entries": 1, "codes": 1})
        self.assertEqual(
            purge.summary(), "1 ancien résident, 1 entrée du journal, 1 code ou essai."
        )

    def test_nothing_to_do_writes_nothing(self):
        User.objects.filter(pk=self.old.pk).update(is_active=True)
        Stay.objects.filter(resident=self.old).update(departure=None)
        result = retention.run(apply=True, now=self.now)
        self.assertEqual(result.total(), 0)
        self.assertFalse(AuditEntry.objects.exists())

    @override_settings(RETENTION_DAYS={"former_residents": 30})
    def test_durations_come_from_the_settings(self):
        self.assertEqual(retention.days("former_residents"), 30)
        self.assertEqual(retention.days("codes"), 30)  # the default
        self.assertEqual(set(retention.former_residents(self.now)), {self.old, self.recent})

    def test_command(self):
        out = StringIO()
        call_command("purge_personal_data", stdout=out)
        self.assertEqual(
            out.getvalue().strip(),
            "À supprimer : 1 ancien résident. Rien n'est supprimé sans --apply.",
        )
        self.assertTrue(User.objects.filter(pk=self.old.pk).exists())
        out = StringIO()
        call_command("purge_personal_data", "--apply", stdout=out)
        self.assertEqual(out.getvalue().strip(), "Supprimé : 1 ancien résident.")
        self.assertFalse(User.objects.filter(pk=self.old.pk).exists())


class PageTests(RetentionTestCase):
    def test_open_to_all(self):
        response = self.client.get(PAGE)
        save_page("privacy-data", response)
        self.assertContains(response, "<h1>Vos données</h1>", html=True)
        self.assertContains(response, "1 an après le départ")
        self.assertContains(response, "6 mois après sa clôture")
        self.assertContains(response, "Adressez-vous à l'accueil de la résidence.")
        self.assertContains(self.client.get(reverse("access:login")), PAGE)

    @override_settings(
        RETENTION_DAYS={"former_residents": 730, "codes": 7},
        PRIVACY_CONTACT="donnees@example.org",
    )
    def test_durations_and_contact_from_the_settings(self):
        response = self.client.get(PAGE)
        self.assertContains(response, "2 ans après le départ")
        self.assertContains(response, "<dd>7 jours après leur fin</dd>", html=True)
        self.assertContains(response, 'href="mailto:donnees@example.org"')

    def test_from_the_account_pages(self):
        resident = make_user("lea", first_name="Léa")
        Stay.objects.create(
            resident=resident, room=Room.objects.create(number="204", floor=self.room.floor)
        )
        log_in_verified(self.client, resident)
        self.assertContains(self.client.get(reverse("account")), PAGE)
        response = self.client.get(PAGE)
        save_page("privacy-data-resident", response)
        self.assertContains(response, 'class="resident-nav')
        log_in_verified(self.client, self.karim)
        response = self.client.get(PAGE)
        save_page("privacy-data-staff", response)
        self.assertContains(response, "Espace équipe")
