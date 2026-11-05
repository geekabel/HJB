from datetime import date

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user

from .models import Floor, Room, Stay
from .services import assign_room, current_stay

D1 = date(2026, 9, 1)
D2 = date(2026, 10, 1)
D3 = date(2026, 11, 1)


def codes(error, field):
    return [e.code for e in error.error_dict.get(field, [])]


class HousingTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ground = Floor.objects.create(number=0)
        cls.f3 = Floor.objects.create(number=3)
        cls.r312 = Room.objects.create(number="312", floor=cls.f3)
        cls.r304 = Room.objects.create(number="304", floor=cls.f3)
        cls.awa = make_user("awa", first_name="Awa", last_name="Koné")
        cls.ines = make_user("ines", first_name="Inès", last_name="Martin")


class LabelsTests(HousingTestCase):
    def test_floors(self):
        self.assertEqual(str(self.ground), "Rez-de-chaussée")
        self.assertEqual(str(Floor(number=1)), "1er étage")
        self.assertEqual(str(self.f3), "3e étage")
        self.assertEqual(self.f3.short_label, "3e")
        self.assertEqual(str(Floor(number=2, name="Aile nord")), "Aile nord")

    def test_room_number_cleaned(self):
        room = Room(number=" 12b ", floor=self.ground)
        room.full_clean()
        self.assertEqual(room.number, "12B")


class ConstraintsTests(HousingTestCase):
    """The rules hold even without going through validation (database)."""

    def test_one_room_one_current_stay(self):
        Stay.objects.create(resident=self.awa, room=self.r312, arrival=D1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Stay.objects.create(resident=self.ines, room=self.r312, arrival=D2)

    def test_one_resident_one_current_stay(self):
        Stay.objects.create(resident=self.awa, room=self.r312, arrival=D1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Stay.objects.create(resident=self.awa, room=self.r304, arrival=D2)

    def test_departure_before_arrival_refused(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Stay.objects.create(resident=self.awa, room=self.r312, arrival=D2, departure=D1)

    def test_history_allowed(self):
        Stay.objects.create(resident=self.awa, room=self.r312, arrival=D1, departure=D2)
        Stay.objects.create(resident=self.ines, room=self.r312, arrival=D2)
        Stay.objects.create(resident=self.awa, room=self.r304, arrival=D2)
        self.assertEqual(Stay.objects.current().count(), 2)


class ValidationTests(HousingTestCase):
    """full_clean() gives clear messages before reaching the database."""

    def test_constraint_messages(self):
        Stay.objects.create(resident=self.awa, room=self.r312, arrival=D1)
        with self.assertRaises(ValidationError) as ctx:
            Stay(resident=self.ines, room=self.r312, arrival=D2).full_clean()
        self.assertIn("room_occupied", [e.code for e in ctx.exception.error_dict["__all__"]])
        with self.assertRaises(ValidationError) as ctx:
            Stay(resident=self.awa, room=self.r304, arrival=D2).full_clean()
        self.assertIn(
            "resident_already_housed", [e.code for e in ctx.exception.error_dict["__all__"]]
        )

    def test_closed_room(self):
        self.r304.active = False
        self.r304.save()
        with self.assertRaises(ValidationError) as ctx:
            Stay(resident=self.awa, room=self.r304, arrival=D1).full_clean()
        self.assertEqual(codes(ctx.exception, "room"), ["room_closed"])
        # A past stay in a room closed since then can still be entered.
        Stay(resident=self.awa, room=self.r304, arrival=D1, departure=D2).full_clean()

    def test_overlap_in_the_same_room(self):
        Stay.objects.create(resident=self.awa, room=self.r312, arrival=D1, departure=D3)
        with self.assertRaises(ValidationError) as ctx:
            Stay(resident=self.ines, room=self.r312, arrival=D2).full_clean()
        self.assertEqual(codes(ctx.exception, "room"), ["room_overlap"])
        with self.assertRaises(ValidationError):
            Stay(resident=self.ines, room=self.r312, arrival=D1, departure=D2).full_clean()

    def test_same_handover_day_allowed(self):
        Stay.objects.create(resident=self.awa, room=self.r312, arrival=D1, departure=D2)
        Stay(resident=self.ines, room=self.r312, arrival=D2).full_clean()

    def test_overlap_for_the_same_person(self):
        Stay.objects.create(resident=self.awa, room=self.r312, arrival=D1, departure=D3)
        with self.assertRaises(ValidationError) as ctx:
            Stay(resident=self.awa, room=self.r304, arrival=D2, departure=D3).full_clean()
        self.assertEqual(codes(ctx.exception, "resident"), ["resident_overlap"])

    def test_past_stay_crosses_a_current_stay(self):
        Stay.objects.create(resident=self.awa, room=self.r312, arrival=D2)
        with self.assertRaises(ValidationError) as ctx:
            Stay(resident=self.ines, room=self.r312, arrival=D1, departure=D3).full_clean()
        self.assertEqual(codes(ctx.exception, "room"), ["room_overlap"])


class FreeRoomsTests(HousingTestCase):
    def test_free(self):
        # 312 occupied, 304 free, 305 closed, 306 free after a departure.
        Stay.objects.create(resident=self.awa, room=self.r312, arrival=D1)
        Room.objects.create(number="305", floor=self.f3, active=False)
        r306 = Room.objects.create(number="306", floor=self.f3)
        Stay.objects.create(resident=self.ines, room=r306, arrival=D1, departure=D2)
        self.assertQuerySetEqual(Room.objects.free(), ["304", "306"], transform=lambda r: r.number)


class AssignRoomTests(HousingTestCase):
    def test_first_arrival(self):
        stay = assign_room(self.awa, self.r312, D1)
        self.assertEqual((stay.room, stay.arrival, stay.departure), (self.r312, D1, None))

    def test_internal_move(self):
        assign_room(self.awa, self.r312, D1)
        new = assign_room(self.awa, self.r304, D2)
        self.assertEqual(new.room, self.r304)
        old = self.awa.stays.get(room=self.r312)
        self.assertEqual(old.departure, D2)
        self.assertEqual(current_stay(self.awa), new)

    def test_fix_on_the_same_day(self):
        first = assign_room(self.awa, self.r312, D1)
        fixed = assign_room(self.awa, self.r304, D1)
        self.assertEqual(fixed.pk, first.pk)
        self.assertEqual(self.awa.stays.count(), 1)

    def test_same_room_has_no_effect(self):
        first = assign_room(self.awa, self.r312, D1)
        self.assertEqual(assign_room(self.awa, self.r312, D2).pk, first.pk)

    def test_occupied_room_refused_without_changing_anything(self):
        assign_room(self.awa, self.r312, D1)
        assign_room(self.ines, self.r304, D1)
        with self.assertRaises(ValidationError):
            assign_room(self.ines, self.r312, D2)
        # The transaction cancels the end of the stay in 304.
        self.assertEqual(current_stay(self.ines).room, self.r304)

    def test_date_before_the_current_stay(self):
        assign_room(self.awa, self.r312, D2)
        with self.assertRaises(ValidationError):
            assign_room(self.awa, self.r304, D1)


class AdminTests(HousingTestCase):
    def setUp(self):
        admin = make_user("chef", Role.ADMIN, is_staff=True, is_superuser=True)
        log_in_verified(self.client, admin)

    def test_admin_pages(self):
        Stay.objects.create(resident=self.awa, room=self.r312, arrival=D1)
        for name in ["floor", "room", "stay"]:
            with self.subTest(name=name):
                response = self.client.get(reverse(f"admin:housing_{name}_changelist"))
                self.assertEqual(response.status_code, 200)
        response = self.client.get(reverse("admin:housing_room_changelist"), {"occupancy": "free"})
        self.assertContains(response, "304")
        self.assertNotContains(response, ">312<")
        # A closed and empty room is neither free nor occupied.
        Room.objects.create(number="399", floor=self.f3, active=False)
        response = self.client.get(
            reverse("admin:housing_room_changelist"), {"occupancy": "occupied"}
        )
        self.assertEqual([r.number for r in response.context["cl"].result_list], ["312"])
        response = self.client.get(reverse("admin:housing_floor_change", args=[self.f3.pk]))
        self.assertEqual(response.status_code, 200)

    def test_add_a_floor_and_its_rooms(self):
        response = self.client.post(
            reverse("admin:housing_floor_add"),
            {
                "number": "1",
                "name": "",
                "visit_order": "1",
                "rooms-TOTAL_FORMS": "2",
                "rooms-INITIAL_FORMS": "0",
                "rooms-0-number": "101",
                "rooms-0-active": "on",
                "rooms-1-number": "102",
                "rooms-1-active": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            list(Floor.objects.get(number=1).rooms.values_list("number", flat=True)),
            ["101", "102"],
        )
