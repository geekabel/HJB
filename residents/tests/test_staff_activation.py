"""Activation code and return of a former resident, staff side (card T11)."""

from datetime import date

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format

from accounts.activation_codes import redeem_code
from accounts.models import ActivationCode
from accounts.roles import Role
from accounts.tests.helpers import confirm_now, log_in_verified, make_user
from audit.models import Action, AuditEntry
from housing.models import Floor, Room, Stay
from housing.services import current_stay
from residents.departure import record_departure
from sms.providers import memory
from tools.html_capture import save_page

from .test_import import csv_


class StaffTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.front_desk = make_user("nadia", Role.FRONT_DESK, first_name="Nadia", last_name="B.")
        f3 = Floor.objects.create(number=3)
        cls.r312 = Room.objects.create(number="312", floor=f3)
        cls.r304 = Room.objects.create(number="304", floor=f3)
        cls.awa = make_user("awa.kone", first_name="Awa", last_name="Koné", phone="+33612345647")
        Stay.objects.create(resident=cls.awa, room=cls.r312, arrival=date(2026, 9, 1))

    def setUp(self):
        log_in_verified(self.client, self.front_desk)
        confirm_now(self.client)  # a code or a cut access asks for it (card T37)

    def code_url(self, resident=None):
        return reverse("residents:activation_code", args=[(resident or self.awa).pk])

    def token(self, resident=None):
        """Token of the "Générer" button, as the profile gives it."""
        response = self.client.get(reverse("residents:detail", args=[(resident or self.awa).pk]))
        return response.context["code_token"]

    def issue(self, resident=None, **kwargs):
        return self.client.post(self.code_url(resident), {"token": self.token(resident)}, **kwargs)


class ActivationCodeTests(StaffTestCase):
    def test_profile_section(self):
        response = self.client.get(reverse("residents:detail", args=[self.awa.pk]))
        self.assertContains(response, "Aucun code remis pour l'instant.")
        self.assertContains(response, f'action="{self.code_url()}"')

    def test_issue_and_printable_sheet(self):
        response = self.issue()
        save_page("residents-activation-code", response)
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        code = response.context["code"]
        self.assertContains(response, f'<p class="code-sheet__code">{code}</p>', html=True)
        self.assertContains(response, "http://testserver/activer/")
        self.assertContains(response, "<svg")
        self.assertContains(response, "Ce code ne s'affichera qu'une fois.")
        # The code is never kept in plain text, not even in the session.
        from django.contrib.sessions.models import Session

        for session in Session.objects.all():
            self.assertNotIn(code, str(session.get_decoded()))
        # The code works, once.
        self.assertEqual(redeem_code(code, "192.0.2.1").user, self.awa)
        entry = AuditEntry.objects.get(action=Action.ACTIVATION_CODE_ISSUED)
        self.assertEqual(entry.actor, self.front_desk)
        # The profile shows the state without ever showing the code again.
        response = self.client.get(reverse("residents:detail", args=[self.awa.pk]))
        self.assertContains(response, "Dernier code utilisé le")
        self.assertNotContains(response, code)

    def test_resending_the_form_does_not_change_the_code(self):
        token = self.token()
        self.client.post(self.code_url(), {"token": token})
        handed_digest = ActivationCode.objects.get().digest
        # Page reload: the same form is sent again.
        response = self.client.post(self.code_url(), {"token": token}, follow=True)
        self.assertRedirects(response, reverse("residents:detail", args=[self.awa.pk]))
        self.assertContains(response, "Ce code a déjà été généré : il reste valable.")
        self.assertEqual(
            list(ActivationCode.objects.valid().values_list("digest", flat=True)),
            [handed_digest],
        )

    def test_without_token_or_token_of_another_resident(self):
        lina = make_user("lina")
        self.assertEqual(self.client.post(self.code_url()).status_code, 302)
        lina_token = self.token(lina)
        self.assertEqual(self.client.post(self.code_url(), {"token": lina_token}).status_code, 302)
        self.assertFalse(ActivationCode.objects.exists())

    def test_two_tabs(self):
        token_1, token_2 = self.token(), self.token()
        self.assertEqual(self.client.post(self.code_url(), {"token": token_1}).status_code, 200)
        self.assertEqual(self.client.post(self.code_url(), {"token": token_2}).status_code, 200)
        self.assertEqual(ActivationCode.objects.valid().count(), 1)  # the second one replaces

    def test_pending_code_on_the_profile(self):
        self.issue()
        response = self.client.get(reverse("residents:detail", args=[self.awa.pk]))
        self.assertContains(response, "Code en attente")
        self.assertContains(response, "remis par Nadia B.")
        self.assertContains(response, "Générer un nouveau code")

    def test_passkey_on_the_profile(self):
        """Card T13: the front desk sees if the activation went as far as the passkey."""
        from access.tests.authenticator import SoftwareAuthenticator

        url = reverse("residents:detail", args=[self.awa.pk])
        self.issue()
        ActivationCode.objects.update(used_at=timezone.now())  # code typed, then given up
        self.assertContains(self.client.get(url), "pas allée jusqu'au bout")

        SoftwareAuthenticator().register(self.awa)
        response = self.client.get(url)
        self.assertNotContains(response, "pas allée jusqu")
        self.assertContains(response, "Clé d'accès créée le <time")

    def test_cut_access(self):
        """Lost phone: the front desk logs the device out right away (T13 review)."""
        from django.test import Client

        from access.tests.authenticator import SoftwareAuthenticator

        SoftwareAuthenticator().register(self.awa)
        lost_phone = Client()
        lost_phone.force_login(self.awa)
        self.issue()  # a pending code, that must no longer work
        url = reverse("residents:cut_access", args=[self.awa.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        response = self.client.post(url, follow=True)
        self.assertContains(
            response, "Accès coupé : 1 clé d&#x27;accès supprimée, 1 session fermée."
        )
        self.assertFalse(self.awa.webauthncredential_set.exists())
        self.assertFalse(ActivationCode.objects.valid().exists())
        self.assertEqual(lost_phone.get("/").status_code, 302)
        entry = AuditEntry.objects.get(action=Action.ACCESS_CUT)
        self.assertEqual(entry.summary(), "1 clé d'accès supprimée, 1 session fermée.")

    def test_confirmation_needed(self):
        from access.session_policy import CONFIRMED_AT_KEY

        session = self.client.session
        del session[CONFIRMED_AT_KEY]
        session.save()
        for name in ("residents:cut_access", "residents:activation_code"):
            with self.subTest(name=name):
                response = self.client.post(reverse(name, args=[self.awa.pk]))
                self.assertTrue(response["Location"].startswith(reverse("access:confirm")))
        self.assertFalse(AuditEntry.objects.filter(action=Action.ACCESS_CUT).exists())

    def test_cut_access_restricted(self):
        educator = make_user("eli", Role.EDUCATOR)
        log_in_verified(self.client, educator)
        url = reverse("residents:cut_access", args=[self.awa.pk])
        self.assertEqual(self.client.post(url).status_code, 403)

    def test_never_with_get(self):
        self.assertEqual(self.client.get(self.code_url()).status_code, 405)

    def test_restricted(self):
        for roles in ([Role.EDUCATOR], [Role.MAINTENANCE], []):
            log_in_verified(self.client, make_user(f"u{len(roles)}{roles}", *roles))
            self.assertEqual(self.client.post(self.code_url()).status_code, 403)
        log_in_verified(self.client, make_user("sam", Role.EDUCATOR))
        response = self.client.get(reverse("residents:detail", args=[self.awa.pk]))
        self.assertNotContains(response, "Activation du compte")
        self.assertFalse(ActivationCode.objects.exists())

    def test_not_for_a_disabled_account(self):
        token = self.token()
        record_departure(self.awa, timezone.localdate())
        response = self.client.post(self.code_url(), {"token": token}, follow=True)
        self.assertContains(response, "enregistrez d&#x27;abord le retour")
        self.assertFalse(ActivationCode.objects.exists())

    def test_departure_cancels_the_code(self):
        self.issue()
        record_departure(self.awa, timezone.localdate())
        self.assertFalse(ActivationCode.objects.valid().exists())


class ReturnTests(StaffTestCase):
    def setUp(self):
        super().setUp()
        record_departure(self.awa, timezone.localdate())
        self.url = reverse("residents:return", args=[self.awa.pk])

    def test_return(self):
        response = self.client.get(self.url)
        save_page("residents-return", response)
        self.assertContains(response, "Retour de Awa Koné")
        response = self.client.post(
            self.url,
            {"room": self.r304.pk, "arrival": timezone.localdate().isoformat()},
            follow=True,
        )
        self.assertContains(response, "Le retour est enregistré et le compte réactivé.")
        self.awa.refresh_from_db()
        self.assertTrue(self.awa.is_active)
        self.assertEqual(current_stay(self.awa).room, self.r304)
        entry = AuditEntry.objects.get(action=Action.RESIDENT_RETURNED)
        self.assertEqual(
            entry.summary(), f"Chambre 304, retour le {date_format(timezone.localdate(), 'j F Y')}."
        )
        # The old login does not make the account look activated.
        self.assertIsNone(self.awa.last_login)
        self.assertEqual(self.awa.account_state, "pending")
        # Then a code can be issued.
        self.assertEqual(self.issue().status_code, 200)
        self.assertTrue(ActivationCode.objects.valid().exists())

    def test_link_from_the_profile(self):
        response = self.client.get(reverse("residents:detail", args=[self.awa.pk]))
        self.assertContains(response, f'href="{self.url}"')

    def test_link_visible_without_the_right_to_issue_codes(self):
        from django.contrib.auth.models import Permission

        # Maintenance, plus resident management given by hand: no right
        # on activation codes.
        manager = make_user("gestion", Role.MAINTENANCE)
        manager.user_permissions.set(
            Permission.objects.filter(codename__in=["view_residents", "manage_residents"])
        )
        log_in_verified(self.client, manager)
        response = self.client.get(reverse("residents:detail", args=[self.awa.pk]))
        self.assertContains(response, f'href="{self.url}"')
        self.assertNotContains(response, "Activation du compte")

    def test_not_for_a_current_resident(self):
        lina = make_user("lina")
        response = self.client.get(reverse("residents:return", args=[lina.pk]))
        self.assertRedirects(response, reverse("residents:detail", args=[lina.pk]))

    def test_only_for_resident_managers(self):
        log_in_verified(self.client, make_user("sam", Role.EDUCATOR))
        self.assertEqual(self.client.get(self.url).status_code, 403)


class ImportWithCodesTests(StaffTestCase):
    def setUp(self):
        super().setUp()
        memory.outbox.clear()

    def run_import(self, send_codes):
        self.client.post(
            reverse("residents:import"),
            {"file": csv_("Prénom;Nom;Téléphone\nInès;Martin;07 81 23 45 88\nLéa;Moreau;\n")},
        )
        token = self.client.session["resident_import"]["token"]
        data = {"action": "import", "ready": "2,3", "token": token}
        if send_codes:
            data["send_codes"] = "yes"
        return self.client.post(reverse("residents:import_preview"), data, follow=True)

    def test_option_visible(self):
        self.client.post(reverse("residents:import"), {"file": csv_("Prénom;Nom\nInès;Martin\n")})
        response = self.client.get(reverse("residents:import_preview"))
        self.assertContains(response, 'name="send_codes"')

    def test_without_the_option(self):
        self.run_import(send_codes=False)
        self.assertEqual(memory.outbox, [])
        self.assertFalse(ActivationCode.objects.exists())

    def test_an_unexpected_failure_does_not_break_the_import(self):
        from unittest import mock

        with (
            mock.patch("residents.views.send_code_by_sms", side_effect=RuntimeError("failure")),
            self.assertLogs("residents.views", "ERROR"),
        ):
            response = self.run_import(send_codes=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "2 résidents importés.")
        self.assertContains(response, "1 SMS n&#x27;ont pas pu partir")

    def test_too_many_codes_to_send(self):
        from unittest import mock

        with mock.patch("residents.views.MAX_SMS_CODES", 0):
            response = self.run_import(send_codes=True)
        self.assertContains(response, "aucun SMS n&#x27;est parti")
        self.assertEqual(memory.outbox, [])

    def test_with_the_option(self):
        response = self.run_import(send_codes=True)
        self.assertContains(response, "2 résidents importés.")
        self.assertContains(response, "1 code d&#x27;activation envoyé par SMS.")
        self.assertContains(response, "1 résident(s) sans numéro")
        (sms,) = memory.outbox
        self.assertEqual(sms.number, "+33781234588")
        self.assertEqual(ActivationCode.objects.valid().count(), 1)
