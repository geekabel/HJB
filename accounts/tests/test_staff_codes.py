"""Staff activation code (card T14): admin action and management command."""

import io
import re

from django.core.management import CommandError, call_command
from django.test import Client, TestCase
from django.urls import reverse

from access.tests.authenticator import SoftwareAuthenticator
from accounts.activation_codes import issue_code
from accounts.models import ActivationCode, User
from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user
from activation.tests.test_passkey import json_post
from audit.models import Action, AuditEntry
from sms.providers import memory
from tools.html_capture import save_page

USER_LIST = "/admin/accounts/user/"


class AdminActionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.marie = make_user(
            "marie", Role.ADMIN, is_staff=True, is_superuser=True, first_name="Marie"
        )
        cls.samia = make_user("samia", Role.EDUCATOR, first_name="Samia", phone="+33612345600")
        cls.awa = make_user("awa", phone="+33612345647")

    def setUp(self):
        log_in_verified(self.client, self.marie)

    def run_action(self, *accounts):
        return self.client.post(
            USER_LIST,
            {"action": "issue_staff_code", "_selected_action": [a.pk for a in accounts]},
            follow=True,
        )

    def test_code_for_a_staff_member(self):
        response = self.run_action(self.samia)
        save_page("admin-staff-code", response)
        self.assertContains(response, "Activer votre compte")
        self.assertContains(response, reverse("admin:accounts_user_change", args=[self.samia.pk]))
        self.assertEqual(response["Cache-Control"].count("no-store"), 1)
        code = ActivationCode.objects.get()
        self.assertTrue(code.for_staff)
        self.assertEqual(code.created_by, self.marie)
        entry = AuditEntry.objects.get(action=Action.ACTIVATION_CODE_ISSUED)
        self.assertTrue(entry.summary().startswith("Code du personnel."))

    def test_not_for_a_resident(self):
        response = self.run_action(self.awa)
        self.assertContains(response, "son code se génère depuis sa fiche")
        self.assertFalse(ActivationCode.objects.exists())

    def test_one_account_only(self):
        response = self.run_action(self.samia, self.marie)
        self.assertContains(response, "Choisissez un seul compte.")
        self.assertFalse(ActivationCode.objects.exists())

    def test_reserved_for_administration(self):
        # Technical access, but without the Administration role: the action does not exist.
        from django.contrib.auth.models import Permission

        technician = make_user("tom", Role.MAINTENANCE, is_staff=True)
        technician.user_permissions.add(
            *Permission.objects.filter(codename__in=["view_user", "change_user"])
        )
        client = Client()
        log_in_verified(client, technician)
        self.assertEqual(client.get(USER_LIST).status_code, 200)
        self.assertNotContains(client.get(USER_LIST), "issue_staff_code")
        client.post(
            USER_LIST,
            {"action": "issue_staff_code", "_selected_action": [self.samia.pk]},
        )
        self.assertFalse(ActivationCode.objects.exists())


class RightsReviewTests(TestCase):
    """Cases found by the independent review of T14."""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth.models import Permission

        edit_users = Permission.objects.filter(codename__in=["view_user", "change_user"])
        cls.tom = make_user("tom", Role.MAINTENANCE, is_staff=True)
        cls.tom.user_permissions.add(*edit_users)
        cls.ali = make_user("ali", Role.ADMIN, is_staff=True)
        cls.ali.user_permissions.add(*edit_users)
        cls.marie = make_user("marie", Role.ADMIN, is_staff=True, is_superuser=True)
        cls.samia = make_user("samia", Role.EDUCATOR, phone="+33612345600")

    def test_no_self_promotion(self):
        """Editing accounts does not let someone give themselves roles or rights."""
        from accounts.tests.test_admin import form_data

        log_in_verified(self.client, self.tom)
        url = reverse("admin:accounts_user_change", args=[self.tom.pk])
        page = self.client.get(url)
        self.assertNotContains(page, 'name="roles"')
        self.assertNotContains(page, 'name="is_superuser"')
        self.assertNotContains(page, 'name="is_staff"')
        self.client.post(
            url, form_data(self.tom, roles=[Role.ADMIN], is_staff="on", is_superuser="on")
        )
        tom = User.objects.get(pk=self.tom.pk)
        self.assertEqual(tom.roles, {Role.MAINTENANCE})
        self.assertFalse(tom.is_superuser)
        self.assertFalse(tom.has_perm("accounts.manage_roles"))

    def test_only_a_superuser_can_make_a_superuser(self):
        from accounts.tests.test_admin import form_data

        log_in_verified(self.client, self.ali)
        url = reverse("admin:accounts_user_change", args=[self.ali.pk])
        self.assertContains(self.client.get(url), 'name="roles"')
        self.client.post(
            url, form_data(self.ali, roles=[Role.ADMIN], is_staff="on", is_superuser="on")
        )
        self.assertFalse(User.objects.get(pk=self.ali.pk).is_superuser)

    def test_added_role_keeps_the_staff_code(self):
        """Adding a role to a staff member does not cancel their staff code."""
        from accounts.tests.test_admin import form_data

        issue_code(self.samia, for_staff=True)
        log_in_verified(self.client, self.marie)
        self.client.post(
            reverse("admin:accounts_user_change", args=[self.samia.pk]),
            form_data(self.samia, phone="06 12 34 56 00", roles=[Role.EDUCATOR, Role.FRONT_DESK]),
        )
        self.assertEqual(User.objects.get(pk=self.samia.pk).roles, {Role.EDUCATOR, Role.FRONT_DESK})
        self.assertTrue(ActivationCode.objects.valid().filter(for_staff=True).exists())

    def test_code_of_a_superuser(self):
        log_in_verified(self.client, self.ali)
        response = self.client.post(
            USER_LIST,
            {"action": "issue_staff_code", "_selected_action": [self.marie.pk]},
            follow=True,
        )
        self.assertContains(response, "Seul un super-utilisateur")
        self.assertFalse(ActivationCode.objects.exists())


class StaffActivationTests(TestCase):
    def setUp(self):
        memory.outbox.clear()
        self.samia = make_user("samia", Role.FRONT_DESK, first_name="Samia", phone="+33612345600")

    def test_full_journey(self):
        code = issue_code(self.samia, for_staff=True)
        self.client.post(reverse("activation:enter_code"), {"code": code})
        self.client.post(reverse("activation:phone"), {"action": "send"})
        sms = re.search(r"\b(\d{6})\b", memory.outbox[-1].text).group(1)
        self.client.post(reverse("activation:phone"), {"action": "verify", "code": sms})
        options = json_post(self.client, reverse("activation:passkey_begin")).json()
        response = json_post(
            self.client,
            reverse("activation:passkey_complete"),
            SoftwareAuthenticator().create(options),
        )
        self.assertEqual(response.status_code, 200)
        # Staff session (12 h), verified by the passkey: the staff area opens.
        self.assertEqual(self.client.session.get_expiry_age(), 12 * 3600)
        self.assertRedirects(self.client.get("/"), reverse("dashboard:home"))

    def test_resident_code_refused_for_staff(self):
        self.client.post(reverse("activation:enter_code"), {"code": issue_code(self.samia)})
        self.assertRedirects(
            self.client.get(reverse("activation:phone")), reverse("activation:enter_code")
        )

    def test_staff_code_refused_for_a_resident(self):
        awa = make_user("awa", phone="+33612345647")
        self.client.post(
            reverse("activation:enter_code"), {"code": issue_code(awa, for_staff=True)}
        )
        self.assertRedirects(
            self.client.get(reverse("activation:phone")), reverse("activation:enter_code")
        )


class CommandTests(TestCase):
    def test_first_administrator(self):
        User.objects.create_superuser("marie", phone="+33612345600")
        output = io.StringIO()
        call_command("activation_code", "marie", stdout=output)
        code = re.search(r"[A-Z0-9]{5}-[A-Z0-9]{5}", output.getvalue()).group(0)
        self.assertTrue(ActivationCode.objects.get().for_staff)
        self.assertNotIn(code.replace("-", ""), str(list(ActivationCode.objects.values())))

    def test_errors(self):
        make_user("no.number")
        for username, message in (("unknown", "Aucun compte"), ("no.number", "numéro")):
            with (
                self.subTest(username=username),
                self.assertRaisesMessage(CommandError, message),
            ):
                call_command("activation_code", username, stdout=io.StringIO())
