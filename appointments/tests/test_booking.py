"""Booking a meeting with an educator (card T27)."""

from datetime import date, datetime, time, timedelta
from unittest import mock

from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user
from housing.models import Floor, Room, Stay
from tools.html_capture import save_page

from .. import availability, booking
from ..holidays import easter, holiday_name
from ..models import Absence, Appointment, EducatorSettings

MONDAY = date(2026, 11, 16)
NOW = timezone.make_aware(datetime(2026, 11, 13, 9, 0))  # the Friday before
BOOK = reverse("rdv:book")


def at(day, hour, minute=0):
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


def hours(slots):
    return [timezone.localtime(slot.start).strftime("%H:%M") for slot in slots]


class BookingTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.samia = make_user("samia", Role.EDUCATOR, first_name="Samia")
        cls.julien = make_user("julien", Role.EDUCATOR, first_name="Julien")
        cls.marie = make_user("marie", Role.ADMIN, first_name="Marie")  # not an educator
        cls.ines = make_user("ines", first_name="Inès", last_name="Martin")
        cls.yanis = make_user("yanis", first_name="Yanis")
        floor = Floor.objects.create(number=3)
        Stay.objects.create(
            resident=cls.ines,
            room=Room.objects.create(number="312", floor=floor),
            arrival=date(2026, 9, 1),
        )
        availability.save_grid(cls.samia, ["0-1000", "0-1030", "0-1100", "2-1400"])
        availability.save_grid(cls.julien, ["0-1000", "0-1030"])
        availability.save_grid(cls.marie, ["0-1000"])


class SlotTests(BookingTestCase):
    def test_who_can_be_booked(self):
        self.assertEqual(list(booking.educators()), [self.julien, self.samia])
        self.julien.is_active = False
        self.julien.save()
        availability.save_grid(self.samia, [])
        self.assertEqual(list(booking.educators()), [])

    def test_booked_and_overlapping_times_are_not_free(self):
        Appointment.objects.create(
            educator=self.samia,
            resident=self.yanis,
            start=at(MONDAY, 10, 30),
            end=at(MONDAY, 11),
        )
        self.assertEqual(hours(booking.free_slots([self.samia], MONDAY, NOW)), ["10:00", "11:00"])
        # The length becomes 45 minutes: 10:00-10:45 would overlap 10:30.
        EducatorSettings.objects.create(educator=self.samia, slot_minutes=45)
        self.assertEqual(hours(booking.free_slots([self.samia], MONDAY, NOW)), [])

    def test_absences_and_public_holidays(self):
        self.assertEqual(
            hours(booking.free_slots([self.samia], MONDAY, NOW)), ["10:00", "10:30", "11:00"]
        )
        Absence.objects.create(educator=self.samia, first_day=MONDAY, last_day=MONDAY)
        self.assertEqual(booking.free_slots([self.samia], MONDAY, NOW), [])
        self.assertEqual(hours(booking.free_slots([self.julien], MONDAY, NOW)), ["10:00", "10:30"])
        armistice = date(2026, 11, 11)  # a Wednesday, and a public holiday
        self.assertEqual(holiday_name(armistice), "Armistice 1918")
        self.assertEqual(booking.free_slots([self.samia], armistice, NOW), [])

    def test_easter_and_days_after_it(self):
        reference = {  # earliest and latest possible dates included
            1818: date(1818, 3, 22),
            1943: date(1943, 4, 25),
            2024: date(2024, 3, 31),
            2026: date(2026, 4, 5),
            2027: date(2027, 3, 28),
            2038: date(2038, 4, 25),
            2285: date(2285, 3, 22),
        }
        for year, expected in reference.items():
            self.assertEqual(easter(year), expected, year)
        self.assertEqual(holiday_name(date(2026, 4, 6)), "Lundi de Pâques")
        self.assertEqual(holiday_name(date(2026, 5, 14)), "Ascension")
        self.assertEqual(holiday_name(date(2026, 5, 25)), "Lundi de Pentecôte")
        self.assertEqual(holiday_name(date(2026, 5, 26)), "")

    def test_two_weeks_ahead_at_most(self):
        days = [day for day, _ in booking.days_with_slots([self.samia], NOW)]
        self.assertEqual(days[0], MONDAY)
        self.assertTrue(all(day <= NOW.date() + timedelta(days=booking.DAYS_AHEAD) for day in days))
        self.assertEqual(len(days), 4)  # 2 Mondays and 2 Wednesdays (11 Nov is closed)


class BookTests(BookingTestCase):
    def test_book_then_the_time_is_taken(self):
        meeting = booking.book(self.ines, at(MONDAY, 10), [self.samia], "budget", NOW)
        self.assertEqual(
            (meeting.educator, meeting.end, meeting.reason),
            (self.samia, at(MONDAY, 10, 30), "budget"),
        )
        with self.assertRaisesMessage(booking.BookingRefused, "Ce créneau n'est plus libre."):
            booking.book(self.yanis, at(MONDAY, 10), [self.samia], now=NOW)

    def test_first_free_picks_the_least_busy_educator(self):
        booking.book(self.yanis, at(MONDAY, 10, 30), [self.samia], now=NOW)
        meeting = booking.book(self.ines, at(MONDAY, 10), [self.samia, self.julien], now=NOW)
        self.assertEqual(meeting.educator, self.julien)

    def test_limits(self):
        booking.book(self.ines, at(MONDAY, 10), [self.samia], now=NOW)
        with self.assertRaisesMessage(
            booking.BookingRefused, "Vous avez déjà un rendez-vous à cette heure-là."
        ):
            booking.book(self.ines, at(MONDAY, 10), [self.julien], now=NOW)  # same time, me
        booking.book(self.ines, at(MONDAY, 11), [self.samia], now=NOW)
        with self.assertRaisesMessage(
            booking.BookingRefused,
            "Vous avez déjà 2 rendez-vous à venir. Annulez-en un depuis sa page",
        ):
            booking.book(self.ines, at(MONDAY + timedelta(days=2), 14), [self.samia], now=NOW)
        with self.assertRaisesMessage(booking.BookingRefused, "deux semaines"):
            booking.book(self.yanis, at(MONDAY + timedelta(days=21), 10), [self.samia], now=NOW)
        meeting = booking.book(self.yanis, at(MONDAY, 10, 30), [self.samia], "nonsense", NOW)
        self.assertEqual(meeting.reason, "")  # an unknown reason is dropped

    def test_database_refuses_a_double_booking(self):
        booking.book(self.ines, at(MONDAY, 10), [self.samia], now=NOW)
        with self.assertRaises(IntegrityError):
            Appointment.objects.create(
                educator=self.samia,
                resident=self.yanis,
                start=at(MONDAY, 10),
                end=at(MONDAY, 10, 30),
            )

    def test_the_constraint_has_the_last_word(self):
        """If every check were fooled, the database still refuses, with a clear message."""
        free = booking.free_slots([self.samia], MONDAY, NOW)
        with mock.patch("appointments.booking.free_slots", return_value=free):
            booking.book(self.ines, at(MONDAY, 10), [self.samia], now=NOW)
            with self.assertRaisesMessage(booking.BookingRefused, "Ce créneau vient d'être pris."):
                booking.book(self.yanis, at(MONDAY, 10), [self.samia], now=NOW)
        self.assertEqual(Appointment.objects.count(), 1)

    def _stale_then_real(self, people):
        """free_slots as seen before the locks (stale), then the real one inside."""
        stale = booking.free_slots(people, MONDAY, NOW)
        real = booking.free_slots
        calls = iter([stale])
        return mock.patch(
            "appointments.booking.free_slots",
            side_effect=lambda *args, **kwargs: next(calls, None) or real(*args, **kwargs),
        )

    def test_checked_again_under_the_lock(self):
        # The grid is closed between the first look and the booking.
        with self._stale_then_real([self.samia]):
            availability.save_grid(self.samia, [])
            with self.assertRaisesMessage(booking.BookingRefused, "n'est plus libre"):
                booking.book(self.ines, at(MONDAY, 10), [self.samia], now=NOW)
        # An absence is added in between: same answer.
        availability.save_grid(self.samia, ["0-1000"])
        with self._stale_then_real([self.samia]):
            Absence.objects.create(educator=self.samia, first_day=MONDAY, last_day=MONDAY)
            with self.assertRaisesMessage(booking.BookingRefused, "n'est plus libre"):
                booking.book(self.ines, at(MONDAY, 10), [self.samia], now=NOW)
        self.assertFalse(Appointment.objects.exists())

    def test_first_free_tries_the_next_educator(self):
        """Samia is taken in between: "le premier libre" books Julien instead of refusing."""
        with self._stale_then_real([self.samia, self.julien]):
            Appointment.objects.create(
                educator=self.julien,
                resident=self.yanis,
                start=at(MONDAY, 11),
                end=at(MONDAY, 11, 30),
            )  # Julien is busier: Samia comes first
            Appointment.objects.create(
                educator=self.samia,
                resident=self.yanis,
                start=at(MONDAY, 10),
                end=at(MONDAY, 10, 30),
            )
            meeting = booking.book(self.ines, at(MONDAY, 10), [self.samia, self.julien], now=NOW)
        self.assertEqual(meeting.educator, self.julien)

    def test_fourteen_days(self):
        last = NOW.date() + timedelta(days=booking.DAYS_AHEAD - 1)
        self.assertTrue(all(day <= last for day, _ in booking.days_with_slots([self.samia], NOW)))
        with self.assertRaisesMessage(booking.BookingRefused, "deux semaines"):
            booking.book(
                self.ines,
                at(NOW.date() + timedelta(days=booking.DAYS_AHEAD), 10),
                [self.samia],
                now=NOW,
            )

    def test_departure_cancels_upcoming_meetings(self):
        from residents.departure import record_departure

        booking.book(self.ines, at(MONDAY, 10), [self.samia], now=NOW)
        with mock.patch("django.utils.timezone.now", return_value=NOW):
            record_departure(self.ines, NOW.date())
        self.assertEqual(Appointment.objects.get().status, Appointment.Status.CANCELLED)


class ResidentPageTests(BookingTestCase):
    """With the real clock: the grid is open every weekday morning."""

    def setUp(self):
        every_morning = [f"{day}-{h}" for day in range(5) for h in ("0900", "0930", "1000", "1030")]
        availability.save_grid(self.samia, every_morning)
        availability.save_grid(self.julien, every_morning)

    def test_choose_and_book(self):
        log_in_verified(self.client, self.ines)
        response = self.client.get(BOOK)
        save_page("appointments-book", response)
        self.assertContains(response, "Le premier libre")
        self.assertContains(response, ">Samia</a>")
        self.assertNotContains(response, "Marie")  # not an educator
        first = response.context["first"]
        response = self.client.get(BOOK, {"avec": self.samia.pk})
        save_page("appointments-book-samia", response)
        self.assertContains(response, "Seul l'éducateur le voit.")
        day = timezone.localtime(first.start).date().isoformat()
        hhmm = timezone.localtime(first.start).strftime("%H%M")
        response = self.client.get(BOOK, {"avec": self.samia.pk, "jour": day, "heure": hhmm})
        self.assertContains(response, f'value="{hhmm}" required checked')
        # Design card D5: a task screen; the bar at the bottom shows the time.
        self.assertContains(response, "resident-page--task")
        when = timezone.localtime(first.start)
        self.assertEqual(
            response.context["chosen"].start, first.start, msg="the asked time is free"
        )
        self.assertContains(response, f"à {when:%H:%M}</p>")
        # A time that is not free that day is never shown as chosen.
        response = self.client.get(BOOK, {"avec": self.samia.pk, "jour": day, "heure": "2359"})
        self.assertIsNone(response.context["chosen"])
        self.assertContains(response, "Choisissez une heure")
        response = self.client.post(
            BOOK, {"avec": self.samia.pk, "jour": day, "heure": hhmm, "motif": "papers"}
        )
        meeting = Appointment.objects.get()
        self.assertRedirects(
            response, reverse("rdv:detail", args=[meeting.pk]), fetch_redirect_response=False
        )
        response = self.client.get(reverse("rdv:detail", args=[meeting.pk]))
        save_page("appointments-detail", response)
        self.assertContains(response, "Rendez-vous confirmé.")
        self.assertContains(response, "Démarches administratives")
        # The Rendez-vous tab lists it, with the button to book another one.
        response = self.client.get(reverse("rdv:list"))
        save_page("appointments-overview", response)
        self.assertContains(response, f'href="{reverse("rdv:detail", args=[meeting.pk])}"')
        self.assertContains(response, "Prendre rendez-vous")
        # Design card D6: the next meeting in a card, and the first free
        # times as links that open the booking with the time chosen.
        self.assertEqual(response.context["next_meeting"], meeting)
        free = response.context["next_free"]
        self.assertEqual(len(free), 3)
        first_free = timezone.localtime(free[0].start)
        self.assertContains(
            response,
            f"?avec=libre&amp;jour={first_free:%Y-%m-%d}&amp;heure={first_free:%H%M}",
        )
        # The same time again, by someone else: refused with a clear message.
        log_in_verified(self.client, self.yanis)
        response = self.client.post(
            BOOK, {"avec": self.samia.pk, "jour": day, "heure": hhmm}, follow=True
        )
        self.assertContains(response, "Ce créneau n&#x27;est plus libre.")
        self.assertEqual(self.client.get(reverse("rdv:detail", args=[meeting.pk])).status_code, 404)

    def test_unknown_educator_and_stale_day(self):
        log_in_verified(self.client, self.ines)
        response = self.client.post(
            BOOK, {"avec": self.marie.pk, "jour": "2026-11-16", "heure": "1000"}, follow=True
        )
        self.assertContains(response, "Cet éducateur ne propose plus de rendez-vous.")
        self.assertFalse(Appointment.objects.exists())
        response = self.client.get(BOOK, {"avec": "libre", "jour": "2000-01-03", "heure": "0900"})
        self.assertContains(response, "Ce jour n&#x27;a plus de créneau libre")
        self.assertNotContains(response, " checked>")

    def test_bad_input_and_staff(self):
        log_in_verified(self.client, self.ines)
        response = self.client.post(
            BOOK, {"avec": "libre", "jour": "demain", "heure": "x"}, follow=True
        )
        self.assertContains(response, "Choisissez un jour et une heure.")
        self.assertFalse(Appointment.objects.exists())
        log_in_verified(self.client, self.samia)
        self.assertRedirects(self.client.get(BOOK), reverse("home"), fetch_redirect_response=False)

    def test_nothing_open(self):
        availability.save_grid(self.samia, [])
        availability.save_grid(self.julien, [])
        log_in_verified(self.client, self.ines)
        response = self.client.get(BOOK)
        save_page("appointments-book-empty", response)
        self.assertContains(response, "Aucun éducateur ne propose de rendez-vous pour le moment.")


class StaffPageTests(BookingTestCase):
    def test_educator_sees_own_meetings_and_reason(self):
        booking.book(self.ines, at(MONDAY, 10), [self.samia], "budget", NOW)
        Appointment.objects.filter(resident=self.ines).update(
            start=timezone.now() + timedelta(days=3),
            end=timezone.now() + timedelta(days=3, minutes=30),
        )
        url = reverse("appointments:availability")
        log_in_verified(self.client, self.samia)
        response = self.client.get(url)
        save_page("appointments-availability-meetings", response)
        self.assertContains(response, "Inès Martin · chambre 312")
        self.assertContains(response, "Motif : Budget")
        log_in_verified(self.client, self.julien)
        response = self.client.get(url)
        self.assertNotContains(response, "Inès Martin")
        self.assertContains(response, "Aucun rendez-vous à venir.")

    def test_staff_page_is_never_cached(self):
        log_in_verified(self.client, self.samia)
        response = self.client.get(reverse("appointments:availability"))
        self.assertIn("no-store", response["Cache-Control"])

    def test_absence_dates_within_limits(self):
        log_in_verified(self.client, self.samia)
        add = reverse("appointments:add_absence")
        today = timezone.localdate()
        response = self.client.post(
            add, {"first_day": "2020-01-01", "last_day": "2020-01-02"}, follow=True
        )
        self.assertContains(response, "Cette absence est déjà passée.")
        far = today + timedelta(days=400)
        response = self.client.post(
            add, {"first_day": far.isoformat(), "last_day": far.isoformat()}, follow=True
        )
        self.assertContains(response, "Une absence se déclare un an à l&#x27;avance au plus.")
        self.assertFalse(Absence.objects.exists())

    def test_absences(self):
        soon = timezone.localdate() + timedelta(days=3)  # never in the past, whatever the date
        Appointment.objects.create(
            educator=self.samia, resident=self.ines, start=at(soon, 10), end=at(soon, 10, 30)
        )
        log_in_verified(self.client, self.samia)
        add = reverse("appointments:add_absence")
        response = self.client.post(
            add, {"first_day": soon.isoformat(), "last_day": soon.isoformat()}, follow=True
        )
        self.assertContains(response, "Absence enregistrée")
        self.assertContains(response, "1 rendez-vous déjà pris pendant cette absence")
        absence = Absence.objects.get()
        self.assertEqual(absence.educator, self.samia)
        response = self.client.post(
            add,
            {
                "first_day": (soon + timedelta(days=5)).isoformat(),
                "last_day": (soon + timedelta(days=3)).isoformat(),
            },
            follow=True,
        )
        self.assertContains(response, "Le dernier jour ne peut pas précéder le premier.")
        # Another educator cannot remove it.
        log_in_verified(self.client, self.julien)
        delete = reverse("appointments:delete_absence", args=[absence.pk])
        self.assertEqual(self.client.post(delete).status_code, 404)
        log_in_verified(self.client, self.samia)
        self.client.post(delete)
        self.assertFalse(Absence.objects.exists())
