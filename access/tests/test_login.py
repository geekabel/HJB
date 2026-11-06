"""Passkey login, confirmation, logout, sessions (card T13)."""

import json
import time
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, SESSION_KEY
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.db import SessionStore
from django.core.cache import cache
from django.http import HttpResponse
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from access import session_policy
from access.decorators import recent_confirmation_required
from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user
from audit.models import Action, AuditEntry
from residents.departure import record_departure
from tools.html_capture import save_page

from .authenticator import SoftwareAuthenticator

BEGIN = reverse("access:verify_begin")
COMPLETE = reverse("access:verify_complete")


def json_post(client, url, data=None):
    body = json.dumps(data) if data is not None else ""
    return client.post(url, data=body, content_type="application/json")


class LoginTestBase(TestCase):
    def setUp(self):
        cache.clear()  # rate limit counters (access/rate_limits.py)
        self.awa = make_user("awa", first_name="Awa", last_name="Diallo")
        self.phone = SoftwareAuthenticator()
        self.passkey = self.phone.register(self.awa)

    def log_in(self, client=None, *, next_url="", **response_options):
        client = client or self.client
        options = json_post(client, BEGIN).json()
        url = f"{COMPLETE}?next={next_url}" if next_url else COMPLETE
        return json_post(client, url, self.phone.get(options, **response_options))


class LoginPageTests(LoginTestBase):
    def test_page(self):
        response = self.client.get(reverse("access:login"))
        save_page("login", response)
        self.assertContains(response, "Me connecter avec ma clé d'accès</button>")
        self.assertContains(response, reverse("activation:enter_code"))
        self.assertContains(response, "Téléphone perdu ou changé ?")
        self.assertContains(response, '"mode": "login"')
        self.assertNotContains(response, "resident-nav")

    def test_already_logged_in(self):
        self.client.force_login(self.awa)
        self.assertRedirects(self.client.get(reverse("access:login")), reverse("home"))

    def test_next_page_kept(self):
        response = self.client.get(reverse("access:login"), {"next": "/guide/"})
        self.assertContains(response, '"next": "/guide/"')
        response = self.client.get(reverse("access:login"), {"next": "https://pirate.example/"})
        self.assertContains(response, '"next": ""')


class LoginTests(LoginTestBase):
    def test_options_without_identifier(self):
        options = json_post(self.client, BEGIN).json()
        self.assertEqual(options["rpId"], "localhost")
        # No passkey listed: nothing reveals who has an account.
        self.assertEqual(options.get("allowCredentials", []), [])
        self.assertEqual(options["userVerification"], "required")

    def test_resident_login(self):
        response = self.log_in()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["redirect_url"], reverse("home"))
        client_session = self.client.session
        self.assertEqual(client_session[SESSION_KEY], str(self.awa.pk))
        self.assertEqual(
            client_session[BACKEND_SESSION_KEY], "django_otp_webauthn.backends.WebAuthnBackend"
        )
        self.assertEqual(client_session["otp_device_id"], self.passkey.persistent_id)
        self.assertEqual(
            client_session.get_expiry_age(),
            int(session_policy.RESIDENT_SESSION_LENGTH.total_seconds()),
        )
        self.passkey.refresh_from_db()
        self.assertIsNotNone(self.passkey.last_used_at)
        self.awa.refresh_from_db()
        self.assertIsNotNone(self.awa.last_login)

    def test_staff_login_short_session(self):
        front_desk = make_user("lea", Role.FRONT_DESK)
        self.phone.register(front_desk)
        self.assertEqual(self.log_in().status_code, 200)
        self.assertEqual(self.client.session.get_expiry_age(), settings.SESSION_COOKIE_AGE)
        # The front desk goes straight to the resident list.
        self.assertRedirects(self.client.get(reverse("home")), reverse("residents:list"))

    def test_next_page(self):
        self.assertEqual(self.log_in(next_url="/guide/").json()["redirect_url"], "/guide/")

    def test_external_next_page_ignored(self):
        response = self.log_in(next_url="https://pirate.example/")
        self.assertEqual(response.json()["redirect_url"], reverse("home"))

    def test_new_session_key(self):
        self.client.get(reverse("access:login"))
        before = self.client.session.session_key
        options = json_post(self.client, BEGIN).json()
        json_post(self.client, COMPLETE, self.phone.get(options))
        self.assertNotEqual(self.client.session.session_key, before)


class LoginDeniedTests(LoginTestBase):
    def assert_denied(self, response, status, code):
        self.assertEqual(response.status_code, status, response.content)
        self.assertEqual(response.json()["code"], code)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_unknown_passkey(self):
        self.passkey.delete()  # replaced at the front desk, for example
        with self.assertLogs("django_otp_webauthn", "ERROR"):
            response = self.log_in()
        self.assert_denied(response, 404, "credential_not_found")
        self.assertIn("Passez à l'accueil", response.json()["detail"])

    def test_disabled_account(self):
        self.awa.is_active = False
        self.awa.save()
        response = self.log_in()
        self.assert_denied(response, 403, "user_disabled")
        self.assertEqual(response.json()["detail"], "Ce compte est désactivé. Passez à l'accueil.")

    def test_user_verification_required(self):
        # Without Face ID, fingerprint or PIN: denied, even with the right passkey.
        with self.assertLogs("django_otp_webauthn", "ERROR"):
            response = self.log_in(user_verified=False)
        self.assert_denied(response, 422, "invalid_authentication_response")

    def test_wrong_origin(self):
        with self.assertLogs("django_otp_webauthn", "ERROR"):
            response = self.log_in(origin="https://pirate.example")
        self.assert_denied(response, 422, "invalid_authentication_response")

    def test_no_replay(self):
        options = json_post(self.client, BEGIN).json()
        passkey_response = self.phone.get(options)
        self.assertEqual(json_post(self.client, COMPLETE, passkey_response).status_code, 200)
        other = Client()
        json_post(other, BEGIN)  # another challenge
        with self.assertLogs("django_otp_webauthn", "ERROR"):
            response = json_post(other, COMPLETE, passkey_response)
        self.assertEqual(response.status_code, 422)
        # And without a begin, there is no state at all.
        self.assertEqual(
            json_post(Client(), COMPLETE, passkey_response).json()["code"], "invalid_state"
        )

    def test_without_begin(self):
        self.assert_denied(json_post(self.client, COMPLETE, {"id": "x"}), 400, "invalid_state")

    def test_csrf_required(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(json_post(client, BEGIN).status_code, 403)


class ConfirmationTests(LoginTestBase):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.log_in().status_code, 200)

    def test_page(self):
        response = self.client.get(reverse("access:confirm"), {"next": "/guide/"})
        save_page("login-confirm", response)
        self.assertContains(response, "Confirmer avec ma clé d'accès</button>")
        self.assertContains(response, '"mode": "confirm"')
        self.assertContains(response, '"next": "/guide/"')

    def test_page_without_passkey(self):
        self.passkey.delete()
        response = self.client.get(reverse("access:confirm"))
        self.assertContains(response, "pas encore de clé d'accès")
        self.assertNotContains(response, "passkey.js")

    def test_anonymous(self):
        url = reverse("access:confirm")
        self.assertRedirects(Client().get(url), f"{reverse('access:login')}?next={url}")

    def test_confirmation(self):
        # 11 minutes ago: no longer recent.
        data = self.client.session
        data[session_policy.CONFIRMED_AT_KEY] = time.time() - 11 * 60
        data.save()
        options = json_post(self.client, BEGIN).json()
        # Logged-in person: their passkeys are listed, and verification is still required.
        self.assertEqual(len(options["allowCredentials"]), 1)
        self.assertEqual(options["userVerification"], "required")
        response = json_post(self.client, f"{COMPLETE}?next=/guide/", self.phone.get(options))
        self.assertEqual(response.json()["redirect_url"], "/guide/")
        self.assertLess(time.time() - self.client.session[session_policy.CONFIRMED_AT_KEY], 5)

    def test_passkey_of_another_account(self):
        intruder = SoftwareAuthenticator()
        intruder.register(make_user("ben"))
        options = json_post(self.client, BEGIN).json()
        with self.assertLogs("django_otp_webauthn", "ERROR"):
            response = json_post(self.client, COMPLETE, intruder.get(options))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "credential_user_mismatch")
        self.assertEqual(self.client.session[SESSION_KEY], str(self.awa.pk))


class DecoratorTests(TestCase):
    def setUp(self):
        self.awa = make_user("awa")
        self.view = recent_confirmation_required(lambda request: HttpResponse("secret"))

    def make_request(self, user, confirmed_ago=None):
        request = RequestFactory().get("/wifi/?onglet=1")
        request.user = user
        request.session = SessionStore()
        if confirmed_ago is not None:
            request.session[session_policy.CONFIRMED_AT_KEY] = time.time() - confirmed_ago
        return request

    def test_anonymous(self):
        response = self.view(self.make_request(AnonymousUser()))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(reverse("access:login")))

    def test_without_confirmation(self):
        response = self.view(self.make_request(self.awa))
        self.assertEqual(
            response["Location"], f"{reverse('access:confirm')}?next=%2Fwifi%2F%3Fonglet%3D1"
        )

    def test_confirmation_too_old(self):
        response = self.view(self.make_request(self.awa, confirmed_ago=11 * 60))
        self.assertEqual(response.status_code, 302)

    def test_recent_confirmation(self):
        self.assertEqual(
            self.view(self.make_request(self.awa, confirmed_ago=60)).content, b"secret"
        )

    def test_time_in_the_future_denied(self):
        self.assertEqual(self.view(self.make_request(self.awa, confirmed_ago=-60)).status_code, 302)


class LogoutAndHomeTests(LoginTestBase):
    def test_logout(self):
        self.log_in()
        self.assertEqual(self.client.get(reverse("access:logout")).status_code, 405)
        response = self.client.post(reverse("access:logout"), follow=True)
        self.assertRedirects(response, reverse("access:login"))
        self.assertContains(response, "Vous êtes déconnecté.")
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_home_anonymous(self):
        self.assertRedirects(self.client.get(reverse("home")), f"{reverse('access:login')}?next=/")

    def test_home_resident(self):
        self.log_in()
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Bonjour Awa")
        # How I log in, and logout: on Mon compte (design card D1).
        response = self.client.get(reverse("account"))
        save_page("account-resident", response)
        self.assertContains(response, "Clé d'accès créée le <time")
        self.assertContains(response, "Me déconnecter")


class DepartureTests(LoginTestBase):
    def test_departure_deletes_passkeys(self):
        self.log_in()
        record_departure(self.awa, timezone.localdate())
        self.assertFalse(self.awa.webauthncredential_set.exists())
        entry = AuditEntry.objects.get(action=Action.RESIDENT_DEPARTED)
        self.assertEqual(entry.details["passkeys_removed"], 1)
        self.assertIn("1 clé d'accès supprimée.", entry.summary())
        # The session is closed, and the passkey can no longer log in.
        self.assertRedirects(self.client.get(reverse("home")), f"{reverse('access:login')}?next=/")
        with self.assertLogs("django_otp_webauthn", "ERROR"):
            self.assertEqual(self.log_in(client=Client()).status_code, 404)


class AdminSiteTests(TestCase):
    def test_passkeys_visible_and_read_only(self):
        admin = make_user("admin", Role.ADMIN, is_staff=True, is_superuser=True)
        passkey = SoftwareAuthenticator().register(make_user("awa"))
        log_in_verified(self.client, admin)
        url = reverse("admin:django_otp_webauthn_webauthncredential_changelist")
        self.assertEqual(self.client.get(url).status_code, 200)
        url = reverse("admin:django_otp_webauthn_webauthncredential_change", args=[passkey.pk])
        response = self.client.post(url, {"name": "other", "confirmed": ""})
        self.assertEqual(response.status_code, 403)
        passkey.refresh_from_db()
        self.assertTrue(passkey.confirmed)


class SessionReviewTests(LoginTestBase):
    """Cases found by the independent review (Nov 5)."""

    def test_length_without_activity(self):
        """The expiry date restarts on each request (SESSION_SAVE_EVERY_REQUEST)."""
        from django.contrib.sessions.models import Session

        self.log_in()
        key = self.client.session.session_key
        Session.objects.filter(pk=key).update(expire_date=timezone.now() + timedelta(days=1))
        self.client.get(reverse("home"))
        remaining = Session.objects.get(pk=key).expire_date - timezone.now()
        self.assertGreater(remaining, session_policy.RESIDENT_SESSION_LENGTH - timedelta(minutes=1))

    def test_deleting_the_passkey_in_the_admin_closes_the_sessions(self):
        self.log_in()
        admin = make_user("admin", Role.ADMIN, is_staff=True, is_superuser=True)
        staff_client = Client()
        log_in_verified(staff_client, admin)
        url = reverse("admin:django_otp_webauthn_webauthncredential_delete", args=[self.passkey.pk])
        with self.captureOnCommitCallbacks(execute=True):
            response = staff_client.post(url, {"post": "yes"})
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(self.client.get(reverse("home")), f"{reverse('access:login')}?next=/")
        self.assertEqual(staff_client.get(reverse("admin:index")).status_code, 200)

    def test_csrf_on_complete(self):
        client = Client(enforce_csrf_checks=True)
        response = json_post(client, COMPLETE, {})
        self.assertEqual(response.status_code, 403)
        self.assertNotEqual(response["Content-Type"], "application/json")


class RateLimitTests(LoginTestBase):
    """Card T14: rate limits per IP address."""

    def test_begins_limited(self):
        from unittest import mock

        with mock.patch("access.rate_limits.MAX_BEGINS", 3):
            for _ in range(3):
                self.assertEqual(json_post(self.client, BEGIN).status_code, 200)
            response = json_post(self.client, BEGIN)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["code"], "too_many_attempts")
        self.assertIn("Réessayez dans quelques minutes", response.json()["detail"])
        # Another address is not affected.
        other = Client(REMOTE_ADDR="192.0.2.8")
        with mock.patch("access.rate_limits.MAX_BEGINS", 3):
            self.assertEqual(json_post(other, BEGIN).status_code, 200)

    def test_failures_block_nobody(self):
        """Review T14: blocking after failures made it possible to block the whole wifi."""
        for _ in range(40):
            json_post(Client(), COMPLETE, {})  # empty requests, denied with no effect
        self.assertEqual(self.log_in().status_code, 200)

    def test_ipv6_counted_per_network(self):
        from access.rate_limits import address_group

        self.assertEqual(address_group("2001:db8::1"), address_group("2001:db8::ffff:2"))
        self.assertEqual(address_group("2001:db8::1"), "2001:db8::/64")
        self.assertNotEqual(address_group("2001:db8:0:1::1"), address_group("2001:db8::1"))
        self.assertEqual(address_group("192.0.2.8"), "192.0.2.8")
        self.assertEqual(address_group(""), "unknown")
