"""Staff login with the code of an authenticator app (card T14c)."""

import re
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp_webauthn.utils import get_credential_model

from access import app_code, credentials
from access.services import cut_access
from access.views import MAX_APP_CODE_TRIES, WRONG_APP_CODE
from accounts.activation_codes import issue_code
from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user
from audit.models import Action, AuditEntry
from sms.providers import memory
from tools.html_capture import save_page


def code_of(device):
    return f"{totp(device.bin_key, device.step, device.t0, device.digits, device.drift):06d}"


def next_code(device):
    """The code of the next 30 seconds (each code works once)."""
    device.refresh_from_db()
    TOTPDevice.objects.filter(pk=device.pk).update(last_t=-1, throttling_failure_count=0)
    device.refresh_from_db()
    return code_of(device)


class ActivationTests(TestCase):
    def setUp(self):
        memory.outbox.clear()
        self.marie = make_user("marie", Role.ADMIN, first_name="Marie", phone="+33612345601")

    def reach_step_three(self, user, for_staff=True):
        self.client.post(
            reverse("activation:enter_code"), {"code": issue_code(user, for_staff=for_staff)}
        )
        self.client.post(reverse("activation:phone"), {"action": "send"})
        sms = re.search(r"\b(\d{6})\b", memory.outbox[-1].text).group(1)
        self.client.post(reverse("activation:phone"), {"action": "verify", "code": sms})

    def test_staff_links_an_app(self):
        old = log_in_verified(self.client.__class__(), self.marie)  # an old passkey
        self.reach_step_three(self.marie)
        response = self.client.get(reverse("activation:passkey"))
        self.assertContains(response, "Utiliser une application de codes")
        url = reverse("activation:app_code")
        response = self.client.get(url)
        save_page("activation-app-code", response)
        self.assertContains(response, "<svg")
        self.assertContains(response, "Votre identifiant : <strong>marie</strong>")
        self.assertContains(response, 'aria-current="step">3. Application')
        device = TOTPDevice.objects.get(user=self.marie)
        self.assertFalse(device.confirmed)
        self.assertEqual(len(app_code.secret(device).replace(" ", "")), 32)
        # A wrong code: an error, and the same QR code (the app is already set up).
        response = self.client.post(
            url, {"code": "000000" if code_of(device) != "000000" else "111111"}
        )
        save_page("activation-app-code-error", response)
        self.assertContains(response, "Ce code ne correspond pas.")
        self.assertEqual(TOTPDevice.objects.get(user=self.marie).pk, device.pk)
        response = self.client.post(url, {"code": next_code(device)})
        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)
        device.refresh_from_db()
        self.assertTrue(device.confirmed)
        # Logged in, verified: the staff area opens.
        self.assertEqual(self.client.get(reverse("residents:list")).status_code, 200)
        # The old passkey no longer works; the audit log says so.
        self.assertFalse(get_credential_model().objects.filter(pk=old.pk).exists())
        entry = AuditEntry.objects.get(action=Action.APP_CODE_CREATED)
        self.assertEqual(entry.details, {"previous_removed": 1})

    def test_not_for_residents(self):
        awa = make_user("awa", first_name="Awa", phone="+33612345647")
        self.reach_step_three(awa, for_staff=False)
        response = self.client.get(reverse("activation:passkey"))
        self.assertNotContains(response, "application de codes")
        self.assertRedirects(
            self.client.get(reverse("activation:app_code")), reverse("activation:passkey")
        )
        self.assertFalse(TOTPDevice.objects.exists())

    def test_not_before_the_phone(self):
        self.client.post(
            reverse("activation:enter_code"), {"code": issue_code(self.marie, for_staff=True)}
        )
        self.assertRedirects(
            self.client.get(reverse("activation:app_code")), reverse("activation:phone")
        )


class LoginTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.marie = make_user("marie", Role.ADMIN, first_name="Marie")
        cls.device = TOTPDevice.objects.create(user=cls.marie, name="app", confirmed=True)
        cls.url = reverse("access:login_app_code")

    def setUp(self):
        cache.clear()  # the rate limit counts per address, in the cache

    def test_login_page_links_to_it(self):
        response = self.client.get(reverse("access:login"))
        self.assertContains(response, self.url)

    def test_right_code(self):
        response = self.client.get(self.url)
        save_page("access-login-app-code", response)
        response = self.client.post(self.url, {"username": " marie ", "code": code_of(self.device)})
        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("residents:list")).status_code, 200)
        self.assertEqual(self.client.session.get_expiry_age(), settings.SESSION_COOKIE_AGE)
        # Each code works once.
        self.client.post(reverse("access:logout"))
        response = self.client.post(self.url, {"username": "marie", "code": code_of(self.device)})
        self.assertContains(response, WRONG_APP_CODE)

    def test_same_message_whatever_is_wrong(self):
        awa = make_user("awa")
        resident_device = TOTPDevice.objects.create(user=awa, name="app", confirmed=True)
        inactive = make_user("old", Role.FRONT_DESK, is_active=False)
        inactive_device = TOTPDevice.objects.create(user=inactive, name="app", confirmed=True)
        tries = [
            ("marie", "000000" if code_of(self.device) != "000000" else "111111"),
            ("nobody", "123456"),
            ("awa", code_of(resident_device)),  # a resident never logs in this way
            ("old", code_of(inactive_device)),
            ("marie", "12 34"),
        ]
        for username, code in tries:
            with self.subTest(username=username, code=code):
                response = self.client.post(self.url, {"username": username, "code": code})
                self.assertContains(response, WRONG_APP_CODE)
                self.assertNotIn("_auth_user_id", self.client.session)

    def test_next_and_rate_limit(self):
        response = self.client.post(
            self.url,
            {"username": "marie", "code": code_of(self.device), "next": "/equipe/messages/"},
        )
        self.assertRedirects(response, "/equipe/messages/", fetch_redirect_response=False)
        self.client.post(reverse("access:logout"))
        for _ in range(MAX_APP_CODE_TRIES):
            self.client.post(self.url, {"username": "nobody", "code": "123456"})
        response = self.client.post(self.url, {"username": "marie", "code": next_code(self.device)})
        self.assertContains(response, "Trop d&#x27;essais depuis ce réseau.")

    def test_wrong_codes_slow_down(self):
        wrong = "999999" if code_of(self.device) != "999999" else "888888"
        self.client.post(self.url, {"username": "marie", "code": wrong})
        self.device.refresh_from_db()
        self.assertEqual(self.device.throttling_failure_count, 1)
        # Right after, even the right code waits until the delay is over.
        response = self.client.post(self.url, {"username": "marie", "code": code_of(self.device)})
        self.assertContains(response, WRONG_APP_CODE)

    def test_confirm_a_sensitive_page(self):
        self.client.post(self.url, {"username": "marie", "code": code_of(self.device)})
        session = self.client.session
        session["passkey_confirmed_at"] -= timedelta(minutes=11).total_seconds()
        session.save()
        target = reverse("residents:wifi_import")
        response = self.client.get(target)
        confirm = f"{reverse('access:confirm')}?next={target.replace('/', '%2F')}"
        self.assertRedirects(response, confirm, fetch_redirect_response=False)
        response = self.client.get(confirm)
        save_page("access-confirm-app-code", response)
        self.assertContains(response, "Code de l&#x27;application")
        response = self.client.post(confirm, {"code": next_code(self.device), "next": target})
        self.assertRedirects(response, target, fetch_redirect_response=False)
        self.assertEqual(self.client.get(target).status_code, 200)


class RemovalTests(TestCase):
    def test_lost_phone_removes_the_app_code_too(self):
        marie = make_user("marie", Role.ADMIN)
        TOTPDevice.objects.create(user=marie, name="app", confirmed=True)
        log_in_verified(self.client, marie)
        self.assertEqual(credentials.app_codes(marie).count(), 1)
        cut_access(marie)
        self.assertFalse(TOTPDevice.objects.filter(user=marie).exists())
        self.assertFalse(get_credential_model().objects.filter(user=marie).exists())
