"""Activation, step 3: passkey creation (card T13)."""

import json
import re
from datetime import timedelta

from django.contrib.auth import SESSION_KEY
from django.db.models import F
from django.test import Client, TestCase
from django.urls import reverse
from django_otp_webauthn.utils import get_credential_model

from access.session_policy import RESIDENT_SESSION_LENGTH
from access.tests.authenticator import SoftwareAuthenticator
from accounts.activation_codes import issue_code
from accounts.models import AccountState, PhoneVerification
from accounts.tests.helpers import make_user
from activation import journey
from audit.models import Action, AuditEntry
from sms.providers import memory
from tools.html_capture import save_page

Passkey = get_credential_model()


def activate_up_to_phone(client, person):
    """Steps 1 and 2: front desk code, then SMS code."""
    client.post(reverse("activation:enter_code"), {"code": issue_code(person)})
    client.post(reverse("activation:phone"), {"action": "send"})
    code = re.search(r"\b(\d{6})\b", memory.outbox[-1].text).group(1)
    client.post(reverse("activation:phone"), {"action": "verify", "code": code})


def json_post(client, url, data=None):
    return client.post(
        url,
        data=json.dumps(data) if data is not None else "",
        content_type="application/json",
    )


def create_passkey(client, authenticator):
    """Full step 3. Returns the complete response."""
    options = json_post(client, reverse("activation:passkey_begin")).json()
    return json_post(client, reverse("activation:passkey_complete"), authenticator.create(options))


class PasskeyTestBase(TestCase):
    def setUp(self):
        memory.outbox.clear()
        self.awa = make_user("awa", first_name="Awa", last_name="Diallo", phone="+33612345647")
        self.phone = SoftwareAuthenticator()
        activate_up_to_phone(self.client, self.awa)


class PasskeyStepTests(PasskeyTestBase):
    def test_page(self):
        response = self.client.get(reverse("activation:passkey"))
        save_page("activation-passkey", response)
        self.assertContains(response, 'aria-current="step">3. Clé d\'accès')
        # Text written in the template: not escaped.
        self.assertContains(response, "Créer ma clé d'accès</button>")
        self.assertContains(response, 'id="passkey-config"')
        self.assertContains(response, "ui/js/passkey.js")
        self.assertContains(response, "csrfmiddlewaretoken")
        # The button stays hidden until the script has checked the browser.
        self.assertContains(response, "data-passkey-button hidden")

    def test_options(self):
        options = json_post(self.client, reverse("activation:passkey_begin")).json()
        self.assertEqual(options["rp"], {"name": "Habitat Jeunes Belfort", "id": "localhost"})
        self.assertEqual(options["user"]["displayName"], "Awa Diallo")
        # A "discoverable" passkey is required: login works without an identifier.
        self.assertEqual(options["authenticatorSelection"]["residentKey"], "required")
        self.assertEqual(options["excludeCredentials"], [])

    def test_full_creation(self):
        response = create_passkey(self.client, self.phone)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["redirect_url"], reverse("home"))

        passkey = Passkey.objects.get()
        self.assertEqual(passkey.user, self.awa)
        self.assertTrue(passkey.discoverable)
        self.awa.refresh_from_db()
        self.assertEqual(self.awa.account_state, AccountState.ACTIVE)

        session = self.client.session
        self.assertEqual(session[SESSION_KEY], str(self.awa.pk))
        self.assertEqual(session["otp_device_id"], passkey.persistent_id)
        self.assertNotIn(journey.KEY, session)
        self.assertEqual(session.get_expiry_age(), int(RESIDENT_SESSION_LENGTH.total_seconds()))

        entry = AuditEntry.objects.get(action=Action.PASSKEY_CREATED)
        self.assertEqual(entry.summary(), "Première clé d'accès.")

        response = self.client.get(reverse("home"))
        save_page("home-resident", response)
        self.assertContains(response, "Bonjour Awa")
        self.assertContains(response, "Me déconnecter")

    def test_get_denied(self):
        self.assertEqual(self.client.get(reverse("activation:passkey_begin")).status_code, 405)
        self.assertEqual(self.client.get(reverse("activation:passkey_complete")).status_code, 405)

    def test_csrf_required(self):
        # Same session (phone verified), but no CSRF token: denied by the CSRF
        # check (HTML page), not by the view (JSON response).
        client = Client(enforce_csrf_checks=True)
        client.cookies = self.client.cookies
        for name in ("activation:passkey_begin", "activation:passkey_complete"):
            with self.subTest(name=name):
                response = json_post(client, reverse(name), {})
                self.assertEqual(response.status_code, 403)
                self.assertNotEqual(response["Content-Type"], "application/json")


class PasskeyStepDeniedTests(PasskeyTestBase):
    def test_without_journey(self):
        client = Client()
        response = json_post(client, reverse("activation:passkey_begin"))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "journey")
        self.assertIn("Recommencez", response.json()["detail"])

    def test_without_verified_phone(self):
        client = Client()
        client.post(reverse("activation:enter_code"), {"code": issue_code(self.awa)})
        self.assertEqual(json_post(client, reverse("activation:passkey_begin")).status_code, 403)
        self.assertRedirects(client.get(reverse("activation:passkey")), reverse("activation:phone"))

    def test_complete_without_begin(self):
        response = json_post(self.client, reverse("activation:passkey_complete"), {"id": "x"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "invalid_state")

    def test_unreadable_json(self):
        json_post(self.client, reverse("activation:passkey_begin"))
        response = self.client.post(
            reverse("activation:passkey_complete"),
            data="{not json",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "malformed_request")

    def test_wrong_origin_then_no_replay(self):
        options = json_post(self.client, reverse("activation:passkey_begin")).json()
        trap = self.phone.create(options, origin="https://pirate.example")
        with self.assertLogs("django_otp_webauthn", "ERROR"):
            response = json_post(self.client, reverse("activation:passkey_complete"), trap)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["detail"], "La clé d'accès n'a pas pu être vérifiée. Réessayez."
        )
        # The state was used once: even a good response to the same challenge is denied.
        good = self.phone.create(options)
        response = json_post(self.client, reverse("activation:passkey_complete"), good)
        self.assertEqual(response.json()["code"], "invalid_state")
        self.assertFalse(Passkey.objects.exists())
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_number_changed_before_complete(self):
        options = json_post(self.client, reverse("activation:passkey_begin")).json()
        self.awa.phone = "+33781234588"
        self.awa.save()
        response = json_post(
            self.client, reverse("activation:passkey_complete"), self.phone.create(options)
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Passkey.objects.exists())

    def test_new_code_during_creation(self):
        options = json_post(self.client, reverse("activation:passkey_begin")).json()
        issue_code(self.awa)  # the front desk issues another code: this one no longer counts
        response = json_post(
            self.client, reverse("activation:passkey_complete"), self.phone.create(options)
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Passkey.objects.exists())


class RecoveryTests(PasskeyTestBase):
    """Lost phone: new code at the front desk, new passkey, the old one no longer works."""

    def test_new_passkey_replaces_the_old_one(self):
        create_passkey(self.client, self.phone)
        old_passkey = Passkey.objects.get()
        old_phone = self.client  # session still open on the old phone

        # More than one minute after the first SMS (delay before a new send).
        PhoneVerification.objects.update(created_at=F("created_at") - timedelta(minutes=2))
        new_phone = Client()
        activate_up_to_phone(new_phone, self.awa)
        options = json_post(new_phone, reverse("activation:passkey_begin")).json()
        # Existing passkeys are not excluded: the same device can create it again.
        self.assertEqual(options["excludeCredentials"], [])
        response = json_post(
            new_phone,
            reverse("activation:passkey_complete"),
            SoftwareAuthenticator().create(options),
        )
        self.assertEqual(response.status_code, 200)

        self.assertFalse(Passkey.objects.filter(pk=old_passkey.pk).exists())
        self.assertEqual(Passkey.objects.filter(user=self.awa).count(), 1)
        # The old session is closed, the new one is open.
        self.assertRedirects(
            old_phone.get(reverse("home")),
            f"{reverse('access:login')}?next=/",
        )
        self.assertEqual(new_phone.get(reverse("home")).status_code, 200)
        entry = AuditEntry.objects.filter(action=Action.PASSKEY_CREATED).latest("pk")
        self.assertEqual(entry.summary(), "Remplace 1 ancienne clé, désormais inutilisable.")


class PasskeyReviewTests(PasskeyTestBase):
    """Cases found by the independent review (Nov 5)."""

    def test_verification_required_at_creation(self):
        options = json_post(self.client, reverse("activation:passkey_begin")).json()
        self.assertEqual(options["authenticatorSelection"]["userVerification"], "required")
        # A passkey created without Face ID, fingerprint or PIN could never be used: denied.
        with self.assertLogs("django_otp_webauthn", "ERROR"):
            response = json_post(
                self.client,
                reverse("activation:passkey_complete"),
                self.phone.create(options, user_verified=False),
            )
        self.assertEqual(response.status_code, 422)
        self.assertFalse(Passkey.objects.exists())

    def test_everything_checked_again_under_the_lock(self):
        """A departure committed just before the lock: no passkey is created."""
        from unittest import mock

        from activation import views

        options = json_post(self.client, reverse("activation:passkey_begin")).json()
        real = views._ready_person
        calls = []

        def person_then_nothing(request):
            calls.append(1)
            return real(request) if len(calls) == 1 else None

        with mock.patch.object(views, "_ready_person", person_then_nothing):
            response = json_post(
                self.client, reverse("activation:passkey_complete"), self.phone.create(options)
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(len(calls), 2)
        self.assertFalse(Passkey.objects.exists())
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_account_became_staff(self):
        from accounts.roles import Role, set_roles

        set_roles(self.awa, {Role.FRONT_DESK})
        response = json_post(self.client, reverse("activation:passkey_begin"))
        self.assertEqual(response.status_code, 403)
        self.assertRedirects(
            self.client.get(reverse("activation:passkey")), reverse("activation:enter_code")
        )

    def test_passkey_id_already_saved(self):
        create_passkey(self.client, self.phone)
        existing = Passkey.objects.get()
        PhoneVerification.objects.update(created_at=F("created_at") - timedelta(minutes=2))
        other = Client()
        activate_up_to_phone(other, self.awa)
        options = json_post(other, reverse("activation:passkey_begin")).json()
        trap = SoftwareAuthenticator().create(options, credential_id=bytes(existing.credential_id))
        with self.assertLogs("django_otp_webauthn", "ERROR"):
            response = json_post(other, reverse("activation:passkey_complete"), trap)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "credential_exists")
        self.assertTrue(Passkey.objects.filter(pk=existing.pk).exists())
