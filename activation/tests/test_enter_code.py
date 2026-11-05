"""Activation, step 1: entering the code (card T11)."""

import time

from django.test import TestCase
from django.urls import reverse

from accounts.activation_codes import issue_code
from accounts.models import ActivationCode
from accounts.tests.helpers import make_user
from activation import journey
from tools.html_capture import save_page


class EnterCodeTests(TestCase):
    def setUp(self):
        self.awa = make_user("awa", first_name="Awa", phone="+33612345647")
        self.url = reverse("activation:enter_code")

    def test_page(self):
        response = self.client.get(self.url)
        save_page("activation-enter-code", response)
        self.assertContains(response, "Activer mon compte")
        self.assertContains(response, 'aria-current="step">1. Code reçu')
        self.assertContains(response, "code-from-link.js")
        self.assertNotContains(response, "resident-nav")
        self.assertIn("no-cache", response["Cache-Control"])

    def test_right_code(self):
        code = issue_code(self.awa)
        self.client.get(self.url)
        key_before = self.client.session.session_key
        response = self.client.post(self.url, {"code": code})
        self.assertRedirects(response, reverse("activation:phone"), fetch_redirect_response=False)
        self.assertNotEqual(self.client.session.session_key, key_before)
        self.assertEqual(self.client.session[journey.KEY]["user"], self.awa.pk)
        self.assertIsNotNone(ActivationCode.objects.get().used_at)
        # Not logged in at this point: the passkey will be needed (T13).
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_wrong_code(self):
        response = self.client.post(self.url, {"code": "AAAAA-AAAAA"})
        save_page("activation-enter-code-error", response)
        self.assertContains(response, "Ce code ne marche pas.")
        self.assertContains(response, 'aria-invalid="true"')
        self.assertNotIn(journey.KEY, self.client.session)

    def test_next_step_without_code(self):
        response = self.client.get(reverse("activation:phone"), follow=True)
        self.assertRedirects(response, self.url)
        self.assertContains(response, "saisissez le code remis par l&#x27;accueil")

    def test_journey_limited_to_one_hour(self):
        self.client.post(self.url, {"code": issue_code(self.awa)})
        session = self.client.session
        session[journey.KEY]["started_at"] = time.time() - journey.DURATION - 1
        session.save()
        response = self.client.get(reverse("activation:phone"))
        self.assertRedirects(response, self.url)
