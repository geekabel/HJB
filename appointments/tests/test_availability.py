"""Weekly grid and settings of an educator (card T26)."""

from datetime import date, datetime, time

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user
from tools.html_capture import save_page

from .. import availability
from ..models import Availability, EducatorSettings

URL = reverse("appointments:availability")
THURSDAY = date(2026, 11, 12)


def aware(day, hour, minute=0):
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


class GridTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.samia = make_user("samia", Role.EDUCATOR, first_name="Samia")

    def test_cells_merge_into_ranges(self):
        keys = ["0-1000", "0-1030", "0-1100", "0-1400", "3-1600"]
        keys += ["6-1000", "0-0730", "0-1900", "0-1015", "x-1000", "nonsense", ""]  # ignored
        self.assertEqual(availability.save_grid(self.samia, keys), 3)
        self.assertEqual(
            [str(a) for a in Availability.objects.all()],
            ["lundi 10:00-11:30", "lundi 14:00-14:30", "jeudi 16:00-16:30"],
        )
        self.assertEqual(
            availability.open_cells(self.samia),
            {"0-1000", "0-1030", "0-1100", "0-1400", "3-1600"},
        )
        availability.save_grid(self.samia, ["1-0800"])  # replaces everything
        self.assertEqual([str(a) for a in Availability.objects.all()], ["mardi 08:00-08:30"])

    def test_bookable_times(self):
        availability.save_grid(self.samia, ["3-1000", "3-1030", "3-1100", "3-1600"])
        before = aware(date(2026, 11, 10), 9)  # Tuesday: the Thursday is far

        def times(day=THURSDAY):
            return [
                timezone.localtime(slot.start).strftime("%H:%M")
                for slot in availability.bookable(self.samia, day, before)
            ]

        self.assertEqual(times(), ["10:00", "10:30", "11:00", "16:00"])
        EducatorSettings.objects.create(educator=self.samia, slot_minutes=45)
        self.assertEqual(times(), ["10:00", "10:45"])  # 16:00-16:30 is too short for 45 min
        self.assertEqual(times(date(2026, 11, 13)), [])  # nothing open on Friday

    def test_booking_deadline(self):
        availability.save_grid(self.samia, ["3-1000", "3-1030", "3-1100", "3-1130"])
        same_day = aware(THURSDAY, 8, 45)
        times = lambda: [  # noqa: E731
            timezone.localtime(s.start).strftime("%H:%M")
            for s in availability.bookable(self.samia, THURSDAY, same_day)
        ]
        self.assertEqual(times(), ["11:00", "11:30"])  # 2 hours before
        EducatorSettings.objects.create(
            educator=self.samia, notice=EducatorSettings.Notice.DAY_BEFORE
        )
        self.assertEqual(times(), [])  # not on the same day
        self.assertEqual(
            len(availability.bookable(self.samia, THURSDAY, aware(date(2026, 11, 11), 23, 59))), 4
        )


class PageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.samia = make_user("samia", Role.EDUCATOR, first_name="Samia")
        cls.nadia = make_user("nadia", Role.FRONT_DESK)
        cls.marie = make_user("marie", Role.ADMIN)
        cls.ines = make_user("ines")

    def test_access(self):
        self.assertIn(reverse("access:login"), self.client.get(URL)["Location"])
        for user in (self.nadia, self.ines):
            log_in_verified(self.client, user)
            self.assertIn(self.client.get(URL).status_code, (302, 403), user)
        log_in_verified(self.client, self.samia)
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'href="{URL}" aria-current="page">Rendez-vous</a>')
        self.assertNotContains(response, "Vous n'avez pas le rôle Éducateur")

    def test_save_grid_and_settings(self):
        log_in_verified(self.client, self.samia)
        response = self.client.post(
            URL,
            {"cell": ["0-1000", "0-1030", "4-1400"], "slot_minutes": "45", "notice": "day_before"},
        )
        self.assertRedirects(response, URL, fetch_redirect_response=False)
        self.assertEqual(Availability.objects.filter(educator=self.samia).count(), 2)
        settings = EducatorSettings.objects.get(educator=self.samia)
        self.assertEqual((settings.slot_minutes, settings.notice), (45, "day_before"))
        response = self.client.get(URL)
        save_page("appointments-availability", response)
        self.assertContains(
            response, "Disponibilités enregistrées. Elles se répètent chaque semaine."
        )
        self.assertContains(response, 'value="0-1000" checked')
        self.assertContains(response, 'value="0-1100">')  # closed
        self.assertContains(response, "Lundi de 10:00 à 10:30")
        # Nothing open: said clearly.
        self.client.post(URL, {"slot_minutes": "30", "notice": "2h"})
        response = self.client.get(URL)
        self.assertContains(response, "aucun créneau ouvert, personne ne peut réserver")
        self.assertFalse(Availability.objects.exists())
        # A bad setting: nothing saved.
        response = self.client.post(URL, {"cell": ["0-1000"], "slot_minutes": "20", "notice": "2h"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Availability.objects.exists())

    def test_not_an_educator(self):
        log_in_verified(self.client, self.marie)
        response = self.client.get(URL)
        save_page("appointments-availability-admin", response)
        self.assertContains(response, "Vous n'avez pas le rôle Éducateur")


class ReviewTests(TestCase):
    """Cases raised by the independent review of T26."""

    @classmethod
    def setUpTestData(cls):
        cls.samia = make_user("samia", Role.EDUCATOR, first_name="Samia")
        cls.karim = make_user("karim", Role.EDUCATOR, first_name="Karim")

    def test_duplicates_and_other_spellings_are_ignored(self):
        keys = ["0-1000", "0-1000", "0-1030", "0-1030", "00-1100", "+0-1100", " 0-1100", "0-08000"]
        availability.save_grid(self.samia, keys)
        self.assertEqual([str(a) for a in Availability.objects.all()], ["lundi 10:00-11:00"])

    def test_every_cell_and_the_edges(self):
        availability.save_grid(self.samia, list(availability.CELLS))
        self.assertEqual(
            [str(a) for a in Availability.objects.all()],
            [f"{day} 08:00-19:00" for day in ("lundi", "mardi", "mercredi", "jeudi", "vendredi")],
        )
        availability.save_grid(self.samia, ["0-0800", "0-1830"])
        self.assertEqual(
            [str(a) for a in Availability.objects.all()], ["lundi 08:00-08:30", "lundi 18:30-19:00"]
        )

    def test_clock_changes(self):
        # 29 March and 25 October 2026: the clocks change in Paris.
        availability.save_grid(self.samia, ["0-0800", "4-0800"])
        utc = __import__("datetime").timezone.utc
        cases = {
            date(2026, 3, 27): datetime(2026, 3, 27, 7, 0, tzinfo=utc),  # winter: +1
            date(2026, 3, 30): datetime(2026, 3, 30, 6, 0, tzinfo=utc),  # summer: +2
            date(2026, 10, 23): datetime(2026, 10, 23, 6, 0, tzinfo=utc),
            date(2026, 10, 26): datetime(2026, 10, 26, 7, 0, tzinfo=utc),
        }
        for day, expected in cases.items():
            (slot,) = availability.bookable(self.samia, day, aware(date(2026, 1, 1), 9))
            self.assertEqual(slot.start, expected, day)

    def test_deadline_edges(self):
        availability.save_grid(self.samia, ["3-1000"])
        exactly_two_hours = aware(THURSDAY, 8)
        self.assertEqual(len(availability.bookable(self.samia, THURSDAY, exactly_two_hours)), 1)
        self.assertEqual(len(availability.bookable(self.samia, THURSDAY, aware(THURSDAY, 8, 1))), 0)
        EducatorSettings.objects.create(educator=self.samia, notice="day_before")
        wednesday = date(2026, 11, 11)
        self.assertEqual(
            len(availability.bookable(self.samia, THURSDAY, aware(wednesday, 23, 59))), 1
        )
        self.assertEqual(len(availability.bookable(self.samia, THURSDAY, aware(THURSDAY, 0))), 0)

    def test_access_is_exactly_forbidden(self):
        for role in (Role.FRONT_DESK, Role.MAINTENANCE, Role.MODERATOR):
            user = make_user(f"u-{role}", role)
            log_in_verified(self.client, user)
            self.assertEqual(self.client.get(URL).status_code, 403, role)
        log_in_verified(self.client, make_user("resident"))
        self.assertEqual(self.client.get(URL).status_code, 403)

    def test_csrf_and_only_my_own_grid(self):
        from django.test import Client

        availability.save_grid(self.karim, ["1-0900"])
        client = Client(enforce_csrf_checks=True)
        log_in_verified(client, self.samia)
        response = client.post(URL, {"cell": ["0-1000"], "slot_minutes": "30", "notice": "2h"})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Availability.objects.filter(educator=self.samia).exists())
        log_in_verified(self.client, self.samia)
        self.client.post(
            URL,
            {"cell": ["0-1000"], "slot_minutes": "60", "notice": "2h", "educator": self.karim.pk},
        )
        self.assertEqual([str(a) for a in self.karim.availabilities.all()], ["mardi 09:00-09:30"])
        self.assertFalse(EducatorSettings.objects.filter(educator=self.karim).exists())

    def test_too_short_ranges_are_reported(self):
        log_in_verified(self.client, self.samia)
        self.client.post(
            URL, {"cell": ["0-1000", "2-1400", "2-1430"], "slot_minutes": "60", "notice": "2h"}
        )
        response = self.client.get(URL)
        self.assertContains(
            response,
            "1 créneau trop court pour un rendez-vous de 60 minutes : lundi 10:00-10:30. "
            "Personne ne peut y réserver.",
        )

    def test_invalid_settings_keep_the_cells(self):
        log_in_verified(self.client, self.samia)
        response = self.client.post(
            URL, {"cell": ["0-1000", "4-1500"], "slot_minutes": "20", "notice": "2h"}
        )
        self.assertContains(response, 'value="4-1500" checked')
        self.assertFalse(Availability.objects.exists())
        self.assertFalse(EducatorSettings.objects.exists())
