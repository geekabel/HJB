"""The page "Réglages" of the residence (card T37b)."""

from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils.html import escape

from accounts.roles import Role
from accounts.tests.helpers import confirm_now, log_in_verified, make_user
from audit.models import Action, AuditEntry
from privacy import retention
from residence.models import ResidenceSettings
from sms import service
from tools.html_capture import save_page

URL = reverse("residence:edit")


def data(**changes):
    row = ResidenceSettings.load()
    values = {
        "organization_name": row.organization_name,
        "organization_address": row.organization_address,
        "privacy_contact": row.privacy_contact,
        "emergency_phone": row.emergency_phone,
        "sms_provider": row.sms_provider,
        "summary_hour": row.summary_hour,
    }
    for kind in retention.KINDS:
        values[f"{kind}_days"] = row.retention_days(kind)
    return values | changes


class SettingsPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.marie = make_user("marie", Role.ADMIN, first_name="Marie")
        cls.karim = make_user("karim", Role.FRONT_DESK)

    def setUp(self):
        log_in_verified(self.client, self.marie)
        confirm_now(self.client)

    def test_only_the_administration(self):
        log_in_verified(self.client, self.karim)
        self.assertEqual(self.client.get(URL).status_code, 403)
        log_in_verified(self.client, make_user("ines"))
        self.assertIn(self.client.get(URL).status_code, (302, 403))

    def test_asks_for_a_recent_confirmation(self):
        self.client.logout()
        log_in_verified(self.client, self.marie)  # a new session, not confirmed
        response = self.client.get(URL)
        self.assertTrue(response["Location"].startswith(reverse("access:confirm")))

    def test_change_and_audit(self):
        response = self.client.get(URL)
        save_page("residence-settings", response)
        self.assertContains(response, 'aria-current="page">Réglages')
        self.assertIn("no-store", response["Cache-Control"])
        response = self.client.post(
            URL,
            data(
                emergency_phone="03 84 00 00 00",
                privacy_contact="donnees@example.org",
                former_residents_days=400,
            ),
        )
        self.assertRedirects(response, URL)
        row = ResidenceSettings.load()
        self.assertEqual(row.emergency_phone, "03 84 00 00 00")
        self.assertEqual(retention.days("former_residents"), 400)
        entry = AuditEntry.objects.get(action=Action.SETTINGS_CHANGED)
        self.assertEqual(entry.actor, self.marie)
        self.assertIn("Numéro d'urgence : vide → 03 84 00 00 00.", entry.summary())
        self.assertIn("400", entry.summary())
        # The pages that use them.
        self.assertContains(self.client.get(reverse("privacy")), "mailto:donnees@example.org")
        # Nothing changed: no entry.
        self.client.post(URL, data())
        self.assertEqual(AuditEntry.objects.filter(action=Action.SETTINGS_CHANGED).count(), 1)

    def test_safe_bounds(self):
        response = self.client.post(
            URL, data(audit_log_days=30, codes_days=0, summary_hour=14, emergency_phone="abc")
        )
        self.assertEqual(response.status_code, 200)
        for name in ("audit_log_days", "codes_days", "summary_hour", "emergency_phone"):
            self.assertIn(name, response.context["form"].errors)
        self.assertEqual(retention.days("audit_log"), 365)
        response = self.client.post(URL, data(privacy_contact="nobody@"))
        self.assertIn("privacy_contact", response.context["form"].errors)

    def test_sms_choice_only_among_ready_services(self):
        form = self.client.get(URL).context["form"]
        values = [value for value, _ in form.fields["sms_provider"].choices]
        self.assertEqual(values, ["", "paused"])  # no keys in the tests
        response = self.client.post(URL, data(sms_provider="ovh"))
        self.assertIn("sms_provider", response.context["form"].errors)
        with mock.patch("residence.forms.ready_providers", return_value=["ovh"]):
            form = self.client.get(URL).context["form"]
            self.assertIn("ovh", [v for v, _ in form.fields["sms_provider"].choices])

    def test_sms_paused(self):
        self.client.post(URL, data(sms_provider="paused"))
        provider = service.active_provider()
        self.assertEqual(provider.name, "disabled")
        with self.assertRaisesMessage(service.ConfigurationError, "coupés dans les réglages"):
            service.send_sms("+33612345678", "Bonjour")
        from messaging.sending import sms_ready

        self.assertFalse(sms_ready())

    def test_a_chosen_service_without_keys_falls_back_to_the_server(self):
        ResidenceSettings.objects.filter(pk=1).update(sms_provider="ovh")
        ResidenceSettings.load()
        self.assertEqual(service.active_provider().name, service.configured_provider().name)

    def test_summary_hour(self):
        from reports import reminders

        ResidenceSettings.objects.update_or_create(pk=1, defaults={"summary_hour": 7})
        start, until = reminders.summary_window()
        self.assertEqual((start.hour, until.hour), (7, 10))

    def test_audit_summary_escapes(self):
        self.client.post(URL, data(organization_name="<b>HJB</b>"))
        response = self.client.get(reverse("audit:list"))
        self.assertContains(response, escape("<b>HJB</b>"))
