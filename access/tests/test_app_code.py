"""Staff login with the code of an authenticator app (card T14c)."""

import re
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp_webauthn.utils import get_credential_model

from access import app_code, credentials
from access.services import cut_access
from access.views import MAX_APP_CODE_FAILURES, WRONG_APP_CODE
from accounts.activation_codes import issue_code
from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user
from audit.models import Action, AuditEntry
from sms.providers import memory
from tools.html_capture import save_page


def code_of(device):
    return f"{totp(device.bin_key, device.step, device.t0, device.digits, device.drift):06d}"


def next_code_keep(device):
    """The code of the next 30 seconds, keeping the failure count."""
    TOTPDevice.objects.filter(pk=device.pk).update(last_t=-1)
    device.refresh_from_db()
    return code_of(device)


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

    def wrong(self):
        return "999999" if code_of(self.device) != "999999" else "888888"

    def test_next_and_rate_limit(self):
        response = self.client.post(
            self.url,
            {"username": "marie", "code": code_of(self.device), "next": "/equipe/messages/"},
        )
        self.assertRedirects(response, "/equipe/messages/", fetch_redirect_response=False)
        self.client.post(reverse("access:logout"))
        # Another site in "next" is ignored.
        response = self.client.post(
            self.url,
            {"username": "marie", "code": next_code(self.device), "next": "https://evil.example/"},
        )
        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)
        self.client.post(reverse("access:logout"))
        # Wrong tries on "nobody" never block marie, even from the same network.
        for _ in range(MAX_APP_CODE_FAILURES):
            self.client.post(self.url, {"username": "nobody", "code": "123456"})
        response = self.client.post(self.url, {"username": "nobody", "code": "123456"})
        self.assertContains(response, "Trop d&#x27;essais depuis ce réseau.")
        response = self.client.post(self.url, {"username": "marie", "code": next_code(self.device)})
        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)

    def test_wrong_codes_slow_down_but_not_for_days(self):
        self.client.post(self.url, {"username": "marie", "code": self.wrong()})
        self.device.refresh_from_db()
        self.assertEqual(self.device.throttling_failure_count, 1)
        # Right after, the right code is told to wait (only the right one).
        response = self.client.post(self.url, {"username": "marie", "code": code_of(self.device)})
        self.assertContains(response, "Code juste, mais il y a eu des essais faux")
        response = self.client.post(self.url, {"username": "marie", "code": self.wrong()})
        self.assertContains(response, WRONG_APP_CODE)
        # Many wrong codes over time: the wait stops at 8.5 minutes.
        for _ in range(20):
            TOTPDevice.objects.filter(pk=self.device.pk).update(
                throttling_failure_timestamp=timezone.now() - timedelta(days=1)
            )
            cache.clear()
            self.client.post(self.url, {"username": "marie", "code": self.wrong()})
        self.device.refresh_from_db()
        self.assertEqual(self.device.throttling_failure_count, app_code.MAX_FAILURES)
        TOTPDevice.objects.filter(pk=self.device.pk).update(
            throttling_failure_timestamp=timezone.now() - timedelta(minutes=9)
        )
        response = self.client.post(
            self.url, {"username": "marie", "code": next_code_keep(self.device)}
        )
        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)
        # The audit log noted the account once.
        self.assertEqual(AuditEntry.objects.filter(action=Action.APP_CODE_FAILURES).count(), 1)

    def test_malformed_code_counts_as_wrong(self):
        self.client.post(self.url, {"username": "marie", "code": "12 34"})
        self.device.refresh_from_db()
        self.assertEqual(self.device.throttling_failure_count, 1)

    def test_unconfirmed_app_code_never_logs_in(self):
        karim = make_user("karim", Role.FRONT_DESK)
        half = TOTPDevice.objects.create(user=karim, name="app", confirmed=False)
        response = self.client.post(self.url, {"username": "karim", "code": code_of(half)})
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


class ConfirmTests(TestCase):
    def test_wrong_code_and_no_form_for_a_resident(self):
        marie = make_user("marie", Role.ADMIN)
        device = TOTPDevice.objects.create(user=marie, name="app", confirmed=True)
        self.client.post(
            reverse("access:login_app_code"), {"username": "marie", "code": code_of(device)}
        )
        wrong = "999999" if code_of(device) != "999999" else "888888"
        response = self.client.post(reverse("access:confirm"), {"code": wrong, "next": "/"})
        self.assertContains(response, "Ce code ne correspond pas.")
        awa = make_user("awa")
        TOTPDevice.objects.create(user=awa, name="app", confirmed=True)
        log_in_verified(self.client, awa)
        response = self.client.get(reverse("access:confirm"))
        self.assertNotContains(response, 'name="code"')


class AdminTests(TestCase):
    def test_no_add_no_change_no_key(self):
        root = make_user("root", is_staff=True, is_superuser=True)
        marie = make_user("marie", Role.ADMIN)
        device = TOTPDevice.objects.create(user=marie, name="app", confirmed=True)
        log_in_verified(self.client, root)
        base = "admin:otp_totp_totpdevice"
        self.assertEqual(self.client.get(reverse(f"{base}_add")).status_code, 403)
        response = self.client.get(reverse(f"{base}_change", args=[device.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, device.key)
        self.assertNotContains(response, 'name="confirmed"')
        response = self.client.post(
            reverse(f"{base}_changelist"),
            {"action": "unlock", "_selected_action": [device.pk]},
        )
        self.assertEqual(response.status_code, 302)


class SideEffectTests(TestCase):
    def test_setup_page_closes_nothing(self):
        marie = make_user("marie", Role.ADMIN, phone="+33612345601")
        other = self.client_class()
        log_in_verified(other, marie)  # her phone, logged in
        old_half = TOTPDevice.objects.create(user=marie, name="app", confirmed=False)
        app_code.new_device(marie)  # what each visit of the setup page does
        self.assertFalse(TOTPDevice.objects.filter(pk=old_half.pk).exists())
        self.assertEqual(other.get(reverse("residents:list")).status_code, 200)

    def test_former_staff_loses_the_app_code(self):
        root = make_user("root", is_staff=True, is_superuser=True)
        marie = make_user("marie", Role.FRONT_DESK, first_name="Marie", last_name="D")
        TOTPDevice.objects.create(user=marie, name="app", confirmed=True)
        log_in_verified(self.client, root)
        from accounts.tests.test_admin import form_data

        self.client.post(reverse("admin:accounts_user_change", args=[marie.pk]), form_data(marie))
        marie.refresh_from_db()
        self.assertFalse(marie.groups.exists())
        self.assertFalse(TOTPDevice.objects.filter(user=marie).exists())
