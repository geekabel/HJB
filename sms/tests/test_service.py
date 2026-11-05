from io import StringIO
from unittest import mock

from django.conf import settings
from django.core.checks import run_checks
from django.core.exceptions import ImproperlyConfigured
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, override_settings

from sms.providers import memory
from sms.providers.base import ConfigurationError, SendError, SmsError
from sms.service import MAX_SEGMENTS, send_sms

NUMBER = "+33612345678"


class ServiceTests(SimpleTestCase):
    def setUp(self):
        memory.outbox.clear()

    def test_tests_never_send_a_real_sms(self):
        self.assertEqual(settings.SMS["BACKEND"], "sms.providers.memory.MemoryProvider")

    def test_send(self):
        result = send_sms(NUMBER, "  Bonjour  ")
        (sms,) = memory.outbox
        self.assertEqual((sms.number, sms.text), (NUMBER, "Bonjour"))
        self.assertEqual(result.message_id, sms.message_id)

    def test_refused_before_sending(self):
        cases = [
            ("06 12 34 56 78", "Bonjour", "format international"),
            # Correct E.164 shape, but the number does not exist or is a landline: refused early.
            ("+999999999", "Bonjour", "portable au format international"),
            ("+33123456789", "Bonjour", "portable au format international"),
            (NUMBER, "   ", "vide"),
            (NUMBER, "a" * (153 * MAX_SEGMENTS + 1), "trop long"),
        ]
        for number, text, excerpt in cases:
            with self.subTest(excerpt), self.assertRaisesMessage(SmsError, excerpt) as ctx:
                send_sms(number, text)
            self.assertFalse(ctx.exception.temporary)
            self.assertFalse(ctx.exception.uncertain)
        self.assertEqual(memory.outbox, [])

    def test_log_without_full_number_or_text(self):
        with self.assertLogs("sms.service", "INFO") as logs:
            send_sms(NUMBER, "Code secret 123456")
        self.assertIn("06 •• •• •• 78", logs.output[0])
        self.assertNotIn("12 34 56", logs.output[0])
        self.assertNotIn("123456", logs.output[0])

    def test_failure_is_logged_then_raised(self):
        with (
            mock.patch(
                "sms.providers.memory.MemoryProvider.send",
                side_effect=SendError("refused", temporary=False),
            ),
            self.assertLogs("sms.service", "WARNING"),
            self.assertRaises(SendError),
        ):
            send_sms(NUMBER, "Bonjour")

    @override_settings(SMS={"BACKEND": "sms.providers.ovh.OvhProvider", "OPTIONS": {}})
    def test_incomplete_provider(self):
        with self.assertRaisesMessage(ConfigurationError, "options manquantes"):
            send_sms(NUMBER, "Bonjour")

    @override_settings(SMS={"BACKEND": "sms.nonexistent.Provider"})
    def test_unknown_provider(self):
        with self.assertRaises(ConfigurationError):
            send_sms(NUMBER, "Bonjour")


class SettingTests(SimpleTestCase):
    def test_choice_from_the_environment(self):
        from config.settings.base import sms_setting

        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertTrue(sms_setting("disabled")["BACKEND"].endswith("DisabledProvider"))
            self.assertTrue(sms_setting("console")["BACKEND"].endswith("ConsoleProvider"))
        environ = {"DJANGO_SMS_PROVIDER": "smsgate", "SMSGATE_URL": "http://192.0.2.5:8080"}
        with mock.patch.dict("os.environ", environ, clear=True):
            setting = sms_setting("disabled")
            self.assertTrue(setting["BACKEND"].endswith("SmsGateProvider"))
            self.assertEqual(setting["OPTIONS"]["url"], "http://192.0.2.5:8080")
            self.assertEqual(setting["OPTIONS"]["token"], "")
        with (
            mock.patch.dict("os.environ", {"DJANGO_SMS_PROVIDER": "pirate"}, clear=True),
            self.assertRaises(ImproperlyConfigured),
        ):
            sms_setting("disabled")

    def test_production_does_not_write_sms_by_default(self):
        # prod.py calls sms_setting("disabled"): without a variable, nothing is sent or shown.
        from pathlib import Path

        source = (Path(settings.BASE_DIR) / "config/settings/prod.py").read_text()
        self.assertIn('SMS = sms_setting("disabled")', source)

    def test_runner_forces_the_memory_outbox_in_every_process(self):
        from tools.test_runner import TEST_SMS, HJBTestRunner, force_test_sms

        self.assertIs(HJBTestRunner.parallel_test_suite.process_setup, force_test_sms)
        with override_settings(SMS={"BACKEND": "sms.providers.ovh.OvhProvider"}):
            force_test_sms()
            self.assertEqual(settings.SMS, TEST_SMS)


class ChecksTests(SimpleTestCase):
    def ids(self, **kwargs):
        return [m.id for m in run_checks(tags=["sms"], **kwargs)]

    def test_test_configuration_is_valid(self):
        self.assertEqual(self.ids(), [])

    @override_settings(SMS={"BACKEND": "sms.providers.smsgate.SmsGateProvider", "OPTIONS": {}})
    def test_missing_options(self):
        self.assertEqual(self.ids(), ["sms.E002"])

    @override_settings(SMS={"BACKEND": "nowhere.at_all.Provider"})
    def test_provider_not_found(self):
        self.assertEqual(self.ids(), ["sms.E001"])

    def test_deployment_warning(self):
        for class_path in ("console.ConsoleProvider", "disabled.DisabledProvider"):
            with (
                self.subTest(class_path),
                override_settings(SMS={"BACKEND": f"sms.providers.{class_path}"}),
            ):
                self.assertEqual(self.ids(include_deployment_checks=True), ["sms.W001"])
                self.assertEqual(self.ids(), [])


class SendTestSmsCommandTests(SimpleTestCase):
    def setUp(self):
        memory.outbox.clear()

    def test_send_test_sms(self):
        out = StringIO()
        call_command("send_test_sms", "06 12 34 56 78", "Fête à l\u2019accueil", stdout=out)
        text = out.getvalue()
        self.assertIn("Fournisseur : memory. Codage : UCS-2", text)
        self.assertIn("Caractères qui imposent l'UCS-2 : ê \u2019", text)
        self.assertIn("Envoyé.", text)
        self.assertEqual(memory.outbox[0].number, NUMBER)

    def test_unreadable_number(self):
        with self.assertRaisesMessage(CommandError, "Ce numéro n'existe pas"):
            call_command("send_test_sms", "06 12", "Bonjour", stdout=StringIO())
