import os
import subprocess
import sys

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from accounts.models import User


class UserModelTests(TestCase):
    def test_active_model_is_the_project_model(self):
        self.assertEqual(settings.AUTH_USER_MODEL, "accounts.User")
        self.assertIs(get_user_model(), User)

    def test_create_user_hashes_the_password(self):
        user = User.objects.create_user(username="awa", password="a-strong-password")
        self.assertNotEqual(user.password, "a-strong-password")
        self.assertTrue(user.check_password("a-strong-password"))

    def test_admin_login_page_redirects_to_passkey(self):
        # Card T14: no more password form.
        response = self.client.get("/admin/login/")
        self.assertRedirects(
            response, "/connexion/?next=/admin/login/", fetch_redirect_response=False
        )


class CommonSettingsTests(SimpleTestCase):
    def test_language_and_time_zone(self):
        self.assertEqual(settings.LANGUAGE_CODE, "fr-fr")
        self.assertEqual(settings.TIME_ZONE, "Europe/Paris")
        self.assertTrue(settings.USE_TZ)


class ProductionSettingsTests(SimpleTestCase):
    """Production settings are loaded in a separate process,
    so the settings of the running tests are not touched."""

    def _import_prod(self, **variables):
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("DJANGO_", "POSTGRES_"))
        }
        environment.update(variables)
        return subprocess.run(
            [
                sys.executable,
                "-c",
                "import config.settings.prod as p; print(p.DEBUG, p.ALLOWED_HOSTS)",
            ],
            cwd=settings.BASE_DIR,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_refuses_to_start_without_secret_key(self):
        result = self._import_prod()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_SECRET_KEY", result.stderr)

    def test_refuses_to_start_without_wifi_keys(self):
        # Card T15: without a key, the wifi passwords could not be read.
        result = self._import_prod(DJANGO_SECRET_KEY="test-key", POSTGRES_DB="hjb")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_WIFI_KEYS", result.stderr)

    def test_refuses_to_start_without_database(self):
        # Card T38: production runs on PostgreSQL only.
        result = self._import_prod(DJANGO_SECRET_KEY="test-key")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("POSTGRES_DB", result.stderr)

    def test_refuses_to_start_without_vapid_key(self):
        # Card T19: without the key, no notification could leave.
        result = self._import_prod(
            DJANGO_SECRET_KEY="test-key", DJANGO_WIFI_KEYS="test-wifi-key", POSTGRES_DB="hjb"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_VAPID_PRIVATE_KEY", result.stderr)

    def test_reads_key_and_hosts_from_environment(self):
        result = self._import_prod(
            DJANGO_SECRET_KEY="test-key",
            DJANGO_WIFI_KEYS="test-wifi-key",
            POSTGRES_DB="hjb",
            DJANGO_VAPID_PRIVATE_KEY="test-vapid-key",
            DJANGO_VAPID_CONTACT="mailto:test@example.org",
            DJANGO_ALLOWED_HOSTS="residence.example, www.residence.example",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "False ['residence.example', 'www.residence.example']",
        )
