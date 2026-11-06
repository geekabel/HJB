from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase
from django.urls import reverse

from accounts.models import User
from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user
from tools.html_capture import save_page

from .models import Action, AuditEntry, AuditEntryImmutable
from .service import log_action


class LogActionTests(TestCase):
    def setUp(self):
        self.admin = make_user("marie", Role.ADMIN)
        self.target = make_user("awa")

    def request(self, user, ip="192.0.2.10"):
        request = RequestFactory().get("/", REMOTE_ADDR=ip)
        request.user = user
        return request

    def test_actor_ip_target_and_details(self):
        entry = log_action(
            Action.ROLES_CHANGED,
            target=self.target,
            details={"before": [], "after": ["front_desk"]},
            request=self.request(self.admin),
        )
        entry.refresh_from_db()
        self.assertEqual(entry.actor, self.admin)
        self.assertEqual(entry.actor_label, "marie")
        self.assertEqual(entry.ip_address, "192.0.2.10")
        self.assertEqual(entry.target, self.target)
        self.assertEqual(entry.target_label, "awa")
        self.assertEqual(entry.summary(), "Avant : aucun (résident). Après : Accueil.")

    def test_without_request_or_actor(self):
        entry = log_action(Action.RESIDENT_DEPARTED, target=self.target)
        self.assertIsNone(entry.actor)
        self.assertIsNone(entry.ip_address)

    def test_anonymous(self):
        entry = log_action(Action.RESIDENT_DEPARTED, request=self.request(AnonymousUser()))
        self.assertIsNone(entry.actor)

    def test_cannot_be_changed(self):
        entry = log_action(Action.RESIDENT_DEPARTED, target=self.target)
        entry.target_label = "other"
        with self.assertRaises(AuditEntryImmutable):
            entry.save()
        with self.assertRaises(AuditEntryImmutable):
            entry.delete()

    def test_stays_readable_after_accounts_are_deleted(self):
        log_action(Action.ROLES_CHANGED, target=self.target, request=self.request(self.admin))
        self.target.delete()
        self.admin.delete()
        entry = AuditEntry.objects.get()
        self.assertIsNone(entry.actor)
        self.assertIsNone(entry.target)
        self.assertEqual((entry.actor_label, entry.target_label), ("marie", "awa"))


class RoleChangeLoggedTests(TestCase):
    def test_django_admin_logs_the_change(self):
        admin = User.objects.create_superuser(username="admin", password="test-password")
        marc = make_user("marc", Role.MAINTENANCE)
        log_in_verified(self.client, admin)
        data = {
            "username": "marc",
            "phone": "",
            "is_active": "on",
            "date_joined_0": "2026-11-05",
            "date_joined_1": "09:00:00",
        }
        url = reverse("admin:accounts_user_change", args=[marc.pk])
        self.client.post(url, data | {"roles": [Role.FRONT_DESK, Role.MAINTENANCE]})
        entry = AuditEntry.objects.get()
        self.assertEqual(entry.action, Action.ROLES_CHANGED)
        self.assertEqual(entry.actor, admin)
        self.assertEqual(
            entry.details, {"before": ["maintenance"], "after": ["front_desk", "maintenance"]}
        )
        # Saving without changing the roles adds nothing.
        self.client.post(url, data | {"roles": [Role.FRONT_DESK, Role.MAINTENANCE]})
        self.assertEqual(AuditEntry.objects.count(), 1)


class AuditPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user("marie", Role.ADMIN)
        cls.front_desk = make_user("ines", Role.FRONT_DESK)
        target = make_user("awa")
        log_action(
            Action.ROLES_CHANGED,
            actor=cls.admin,
            target=target,
            details={"before": [], "after": ["front_desk"]},
        )
        log_action(Action.RESIDENT_DEPARTED, actor=cls.admin, target=target)

    def test_administration_only(self):
        url = reverse("audit:list")
        self.assertEqual(self.client.get(url).status_code, 302)
        log_in_verified(self.client, self.front_desk)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_list_and_link_in_the_menu(self):
        log_in_verified(self.client, self.admin)
        response = self.client.get(reverse("audit:list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Avant : aucun (résident). Après : Accueil.")
        self.assertContains(response, "Départ d&#x27;un résident")
        # Text written literally in the template: Django does not escape it.
        self.assertContains(response, 'aria-current="page">Journal</a>')
        # On mobile, the table scrolls: the area must be reachable with the keyboard.
        self.assertContains(response, 'role="region" aria-labelledby="audit-caption" tabindex="0"')
        save_page("audit-log", response)

    def test_filter_by_action(self):
        log_in_verified(self.client, self.admin)
        response = self.client.get(reverse("audit:list"), {"action": Action.RESIDENT_DEPARTED})
        self.assertEqual(len(response.context["page_obj"]), 1)
        # An unknown value is ignored.
        response = self.client.get(reverse("audit:list"), {"action": "<script>"})
        self.assertEqual(len(response.context["page_obj"]), 2)

    def test_no_entry_for_this_action(self):
        log_in_verified(self.client, self.admin)
        response = self.client.get(reverse("audit:list"), {"action": Action.WIFI_PASSWORD_SHOWN})
        self.assertContains(response, "Aucune entrée pour cette action")
        save_page("audit-log-empty", response)

    def test_link_absent_for_other_roles(self):
        log_in_verified(self.client, self.front_desk)
        response = self.client.get(reverse("ui:guide"))
        self.assertNotContains(response, reverse("audit:list"))


class SummaryTests(TestCase):
    """Every entry reads as French words, even an old one with missing details."""

    def test_every_action_with_no_details(self):
        for action in Action:
            with self.subTest(action=action):
                text = AuditEntry(action=action, details={}).summary()
                self.assertTrue(text)
                self.assertNotIn(" : ", text.replace("Avant : ", "").replace("Après : ", ""))

    def test_real_details(self):
        cases = [
            (
                Action.MESSAGE_SENT,
                {"recipients": 2, "push": 0, "sms": 1, "segments": 2, "failed": 1},
                "2 destinataires, 0 notification, 1 SMS (2 facturés), 1 échec.",
            ),
            (Action.MESSAGE_CANCELLED, {"reminder": True}, "Relance annulée."),
            (
                Action.MESSAGE_CANCELLED,
                {"reminder_too_late": True},
                "Relance trop tardive : elle n'est pas partie.",
            ),
            (Action.APP_CODE_CREATED, {"previous_removed": 2}, "Remplace 2 anciens accès."),
            (Action.APP_CODE_FAILURES, {"failures": 5}, "5 codes faux d'affilée."),
            (Action.RESIDENT_RETURNED, {"room": "312"}, "–"),
        ]
        for action, details, expected in cases:
            with self.subTest(action=action, details=details):
                self.assertEqual(AuditEntry(action=action, details=details).summary(), expected)
