"""Activation, step 2: phone verification (card T12)."""

import re

from django.test import TestCase
from django.urls import reverse

from accounts.activation_codes import issue_code
from accounts.models import PhoneVerification
from accounts.tests.helpers import make_user
from activation import journey
from sms.providers import memory
from tools.html_capture import save_page


class PhoneTestBase(TestCase):
    def setUp(self):
        memory.outbox.clear()
        self.awa = make_user("awa", first_name="Awa", phone="+33612345647")
        self.url = reverse("activation:phone")
        self.client.post(reverse("activation:enter_code"), {"code": issue_code(self.awa)})

    def send(self):
        return self.client.post(self.url, {"action": "send"}, follow=True)

    def received_code(self):
        return re.search(r"\b(\d{6})\b", memory.outbox[-1].text).group(1)


class PhoneStepTests(PhoneTestBase):
    def test_before_sending(self):
        response = self.client.get(self.url)
        save_page("activation-phone", response)
        self.assertContains(response, 'aria-current="step">2. Téléphone')
        self.assertContains(response, "06 •• •• •• 47")
        self.assertContains(response, "Recevoir le code par SMS")
        self.assertEqual(memory.outbox, [])  # nothing is sent when the page is only viewed

    def test_full_journey(self):
        response = self.send()
        save_page("activation-phone-code", response)
        self.assertContains(response, "Code envoyé.")
        self.assertContains(response, 'autocomplete="one-time-code"')
        self.assertContains(response, "Possible à partir de <time")
        response = self.client.post(
            self.url, {"action": "verify", "code": self.received_code()}, follow=True
        )
        self.assertRedirects(response, reverse("activation:passkey"))
        save_page("activation-passkey", response)
        self.assertContains(response, "Votre téléphone est vérifié.")
        self.assertContains(response, 'aria-current="step">3. Clé d\'accès')
        self.awa.refresh_from_db()
        self.assertIsNotNone(self.awa.phone_verified_at)
        # Going back to step 2 leads to step 3.
        self.assertRedirects(self.client.get(self.url), reverse("activation:passkey"))

    def test_wrong_code(self):
        self.send()
        response = self.client.post(self.url, {"action": "verify", "code": "000000"})
        if self.received_code() == "000000":
            return
        save_page("activation-phone-error", response)
        self.assertContains(response, "Code incorrect. Il vous reste 4 essais.")
        self.assertContains(response, 'aria-invalid="true"')

    def test_resend_too_soon(self):
        self.send()
        response = self.send()
        self.assertContains(response, "Patientez")
        self.assertEqual(len(memory.outbox), 1)

    def test_no_number(self):
        lina = make_user("lina", first_name="Lina")
        self.client.post(reverse("activation:enter_code"), {"code": issue_code(lina)})
        response = self.client.get(self.url)
        self.assertContains(response, "Aucun numéro n'est enregistré pour vous.")
        self.assertNotContains(response, "Recevoir le code")

    def test_not_my_number(self):
        response = self.client.get(reverse("activation:wrong_number"))
        save_page("activation-wrong-number", response)
        self.assertContains(response, "Passez à l'accueil avec une pièce d'identité.")
        # Viewing the page changes nothing (link prefetch, trapped image...).
        self.assertIn(journey.KEY, self.client.session)

    def test_step_3_without_verification(self):
        self.assertRedirects(self.client.get(reverse("activation:passkey")), self.url)

    def test_codes_are_not_stored_in_clear(self):
        self.send()
        code = self.received_code()
        self.assertNotIn(code, PhoneVerification.objects.get().digest)


class ReviewTests(PhoneTestBase):
    """Cases found by the independent review (Nov 5)."""

    def test_new_activation_code_closes_the_old_session(self):
        issue_code(self.awa)  # the front desk issues a new code (the old one may be stolen)
        response = self.client.post(self.url, {"action": "send"})
        self.assertRedirects(response, reverse("activation:enter_code"))
        self.assertEqual(memory.outbox, [])

    def test_number_changed_after_verification(self):
        self.send()
        self.client.post(self.url, {"action": "verify", "code": self.received_code()})
        self.awa.phone = "+33781234588"
        self.awa.save()
        self.assertRedirects(self.client.get(reverse("activation:passkey")), self.url)
        response = self.client.get(self.url)
        self.assertContains(response, "Recevoir le code par SMS")

    def test_departure_during_activation(self):
        from django.utils import timezone

        from residents.departure import record_departure

        record_departure(self.awa, timezone.localdate())
        self.assertRedirects(self.client.get(self.url), reverse("activation:enter_code"))
