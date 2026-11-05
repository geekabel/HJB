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
