"""Departure of a resident (card T09). Made-up data."""

from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user
from audit.models import Action, AuditEntry
from housing.models import Floor, Room, Stay
from housing.services import current_stay
from residents.departure import (
    close_sessions,
    departure_recorded,
    record_departure,
    session_keys_for,
)
from tools.html_capture import save_page

ARRIVAL = date(2026, 9, 1)


class DepartureTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.front_desk = make_user("nadia", Role.FRONT_DESK)
        f3 = Floor.objects.create(number=3)
        cls.r312 = Room.objects.create(number="312", floor=f3)
        cls.awa = make_user("awa.kone", first_name="Awa", last_name="Koné", phone="+33612345647")
        Stay.objects.create(resident=cls.awa, room=cls.r312, arrival=ARRIVAL)

    def setUp(self):
        log_in_verified(self.client, self.front_desk)

    def url(self):
        return reverse("residents:departure", args=[self.awa.pk])


class ServiceTests(DepartureTestCase):
    def test_full_departure(self):
        # Awa is logged in on two devices.
        phone, computer = Client(), Client()
        phone.force_login(self.awa)
        computer.force_login(self.awa)
        self.assertEqual(Client().session.__class__.__name__, "SessionStore")

        received = []

        def receiver(sender, **kwargs):
            received.append(kwargs)

        departure_recorded.connect(receiver)
        self.addCleanup(departure_recorded.disconnect, receiver)

        on = timezone.localdate()
        stay = record_departure(self.awa, on)

        self.awa.refresh_from_db()
        self.assertFalse(self.awa.is_active)
        self.assertFalse(self.awa.has_usable_password())
        self.assertEqual(stay.departure, on)
        self.assertIsNone(current_stay(self.awa))
        self.assertIn(self.r312, Room.objects.free())
        self.assertEqual(len(received), 1)
        self.assertEqual((received[0]["resident"], received[0]["stay"]), (self.awa, stay))

        entry = AuditEntry.objects.get(action=Action.RESIDENT_DEPARTED)
        self.assertEqual(entry.target, self.awa)
        self.assertEqual(entry.target_label, "Awa Koné (awa.kone)")
        self.assertEqual(entry.details["sessions_closed"], 2)
        self.assertEqual(
            entry.summary(), f"Chambre 312, départ le {on:%d/%m/%Y}. 2 sessions fermées."
        )
        # Both devices are logged out.
        for client in (phone, computer):
            self.assertNotIn("_auth_user_id", client.session)

    def test_other_people_sessions_stay(self):
        log_in_verified(Client(), self.front_desk)
        Client().force_login(self.awa)
        self.assertEqual(close_sessions(session_keys_for(self.awa)), 1)
        self.assertEqual(len(session_keys_for(self.awa)), 0)
        # The one from setUp and this one.
        self.assertEqual(len(session_keys_for(self.front_desk)), 2)

    def test_a_failing_receiver_cancels_everything(self):
        def receiver(sender, **kwargs):
            raise RuntimeError("wifi cannot be cut")

        departure_recorded.connect(receiver)
        self.addCleanup(departure_recorded.disconnect, receiver)
        with self.assertRaises(RuntimeError):
            record_departure(self.awa, timezone.localdate())
        self.awa.refresh_from_db()
        self.assertTrue(self.awa.is_active)
        self.assertIsNotNone(current_stay(self.awa))
        self.assertFalse(AuditEntry.objects.exists())

    def test_without_stay(self):
        lina = make_user("lina")
        self.assertIsNone(record_departure(lina, timezone.localdate()))
        lina.refresh_from_db()
        self.assertFalse(lina.is_active)


class DeparturePageTests(DepartureTestCase):
    def test_confirmation(self):
        response = self.client.get(self.url())
        save_page("residents-departure", response)
        self.assertContains(response, "Départ de Awa Koné")
        self.assertContains(response, "La chambre 312 sera libérée")
        self.assertContains(response, 'class="button button--danger"')
        # A later date is a planned departure (card T21), up to one year ahead.
        limit = timezone.localdate() + timedelta(days=365)
        self.assertContains(response, f'max="{limit.isoformat()}"')
        self.assertContains(response, 'min="2026-09-01"')

    def test_recording(self):
        on = timezone.localdate() - timedelta(days=1)
        response = self.client.post(self.url(), {"departure": on.isoformat()}, follow=True)
        self.assertRedirects(response, reverse("residents:detail", args=[self.awa.pk]))
        save_page("residents-detail-former", response)
        self.assertContains(response, "Le départ de Awa Koné est enregistré.")
        self.assertContains(response, "Cette personne a quitté la résidence le")
        self.assertNotContains(response, 'name="room"')
        self.assertNotContains(response, reverse("residents:departure", args=[self.awa.pk]))
        self.assertEqual(self.awa.stays.get().departure, on)
        entry = AuditEntry.objects.get()
        self.assertEqual(entry.actor, self.front_desk)
        self.assertEqual(entry.ip_address, "127.0.0.1")

    def test_refused_dates(self):
        cases = {
            (timezone.localdate() + timedelta(days=366)).isoformat(): "plus d&#x27;un an",
            "2026-08-31": "avant l&#x27;arrivée dans la chambre (01/09/2026)",
            "": "Ce champ est obligatoire.",
        }
        for value, message in cases.items():
            with self.subTest(value=value):
                response = self.client.post(self.url(), {"departure": value})
                save_page("residents-departure-error", response)
                self.assertContains(response, message)
                self.assertContains(response, "Le départ n'est pas enregistré.")
        self.awa.refresh_from_db()
        self.assertTrue(self.awa.is_active)

    def test_already_left(self):
        record_departure(self.awa, timezone.localdate())
        response = self.client.get(self.url(), follow=True)
        self.assertRedirects(response, reverse("residents:detail", args=[self.awa.pk]))
        self.assertContains(response, "Le départ de cette personne est déjà enregistré.")

    def test_only_for_resident_managers(self):
        log_in_verified(self.client, make_user("sam", Role.EDUCATOR))
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        self.assertEqual(self.client.post(self.url(), {"departure": "2026-11-01"}).status_code, 403)
        response = self.client.get(reverse("residents:detail", args=[self.awa.pk]))
        self.assertNotContains(response, "Enregistrer le départ")

    def test_link_from_the_profile(self):
        response = self.client.get(reverse("residents:detail", args=[self.awa.pk]))
        self.assertContains(response, f'href="{self.url()}"')


class ListAfterDepartureTests(DepartureTestCase):
    def test_former_residents_apart(self):
        record_departure(self.awa, timezone.localdate())
        make_user("lina", first_name="Lina", last_name="Roux")
        response = self.client.get(reverse("residents:list"))
        self.assertEqual([r.username for r in response.context["page_obj"]], ["lina"])
        self.assertContains(response, "1 résident · ")
        self.assertContains(response, '<a href="?account=disabled">1 ancien</a>', html=True)
        response = self.client.get(reverse("residents:list"), {"account": "disabled"})
        self.assertEqual([r.username for r in response.context["page_obj"]], ["awa.kone"])
        self.assertContains(response, "Désactivé")

    def test_former_resident_profile_editable_without_housing(self):
        record_departure(self.awa, timezone.localdate())
        response = self.client.post(
            reverse("residents:detail", args=[self.awa.pk]),
            {"first_name": "Awa", "last_name": "Koné", "phone": "", "email": "a@exemple.fr"},
        )
        self.assertEqual(response.status_code, 302)
        self.awa.refresh_from_db()
        self.assertEqual(self.awa.email, "a@exemple.fr")
        self.assertFalse(self.awa.is_active)
        self.assertIsNone(current_stay(self.awa))
        self.assertEqual(User.objects.get(pk=self.awa.pk).stays.count(), 1)


class ReviewTests(DepartureTestCase):
    """Cases found by the independent review (5 Nov.)."""

    def test_a_profile_opened_before_the_departure_does_not_undo_it(self):
        # The form is prepared (active account), then the departure happens, then it is sent.
        from residents.forms import ResidentForm

        r313 = Room.objects.create(number="313", floor=self.r312.floor)
        form = ResidentForm(
            {
                "first_name": "Awa",
                "last_name": "Koné",
                "phone": "",
                "email": "",
                "room": r313.pk,
                "arrival": timezone.localdate().isoformat(),
            },
            instance=User.objects.get(pk=self.awa.pk),
        )
        self.assertTrue(form.is_valid(), form.errors)
        record_departure(self.awa, timezone.localdate())
        with self.assertRaisesMessage(ValidationError, "vient d'être enregistré"):
            form.save_resident()
        self.awa.refresh_from_db()
        self.assertFalse(self.awa.is_active)
        self.assertFalse(Stay.objects.filter(room=r313).exists())

    def test_changing_the_identity_does_not_reopen_the_account(self):
        from residents.forms import ResidentForm

        before = User.objects.get(pk=self.awa.pk)
        record_departure(self.awa, timezone.localdate())
        # Profile of a former resident (without room fields): only the identity is written.
        form = ResidentForm(
            {"first_name": "Awa", "last_name": "Koné", "phone": "", "email": "a@exemple.fr"},
            instance=User.objects.get(pk=self.awa.pk),
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save_resident()
        self.awa.refresh_from_db()
        self.assertFalse(self.awa.is_active)
        self.assertNotEqual(self.awa.password, before.password)

    def test_account_disabled_elsewhere_but_still_housed(self):
        User.objects.filter(pk=self.awa.pk).update(is_active=False)
        # Still in the list, and its departure can free the room.
        response = self.client.get(reverse("residents:list"))
        self.assertEqual([r.username for r in response.context["page_obj"]], ["awa.kone"])
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        self.client.post(self.url(), {"departure": timezone.localdate().isoformat()})
        self.assertIn(self.r312, Room.objects.free())

    def test_double_departure(self):
        copy = User.objects.get(pk=self.awa.pk)
        record_departure(self.awa, timezone.localdate())
        with self.assertRaisesMessage(ValidationError, "déjà enregistré"):
            record_departure(copy, timezone.localdate())
        self.assertEqual(AuditEntry.objects.count(), 1)

    def test_admin_accounts_never_residents(self):
        chef = User.objects.create_superuser("chef", password="x")
        chef.groups.clear()  # even without a group
        technician = User.objects.create_user("tech", is_staff=True)
        residents = set(User.objects.residents().values_list("username", flat=True))
        self.assertNotIn("chef", residents)
        self.assertNotIn("tech", residents)
        self.assertEqual(
            self.client.get(reverse("residents:departure", args=[chef.pk])).status_code, 404
        )
        self.assertEqual(
            self.client.get(reverse("residents:departure", args=[technician.pk])).status_code,
            404,
        )

    def test_educators_do_not_see_former_residents(self):
        record_departure(self.awa, timezone.localdate())
        log_in_verified(self.client, make_user("sam", Role.EDUCATOR))
        response = self.client.get(reverse("residents:list"), {"account": "disabled"})
        self.assertEqual(list(response.context["page_obj"]), [])
        self.assertNotContains(response, "ancien résident")
        self.assertNotContains(response, 'value="disabled"')
        response = self.client.get(reverse("residents:detail", args=[self.awa.pk]))
        self.assertEqual(response.status_code, 404)
