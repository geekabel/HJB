from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import AccountState, User
from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user
from housing.models import Floor, Room, Stay
from housing.services import current_stay
from residents.forms import free_username
from tools.html_capture import save_page

D1 = date(2026, 9, 1)
D2 = date(2026, 10, 15)


class ResidentsTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.front_desk = make_user("nadia", Role.FRONT_DESK, first_name="Nadia", last_name="B.")
        cls.f1 = Floor.objects.create(number=1)
        cls.f3 = Floor.objects.create(number=3)
        cls.r118 = Room.objects.create(number="118", floor=cls.f1)
        cls.r304 = Room.objects.create(number="304", floor=cls.f3)
        cls.r312 = Room.objects.create(number="312", floor=cls.f3)
        cls.awa = make_user("awa.kone", first_name="Awa", last_name="Koné", phone="+33612345647")
        cls.yanis = make_user("yanis.t", Role.MODERATOR, first_name="Yanis", last_name="Traoré")
        cls.lucas = make_user("lucas.p", first_name="Lucas", last_name="Petit")
        Stay.objects.create(resident=cls.awa, room=cls.r312, arrival=D1)
        Stay.objects.create(resident=cls.yanis, room=cls.r118, arrival=D1)
        # Awa and Yanis have already logged in; Lucas not yet.
        User.objects.filter(pk__in=[cls.awa.pk, cls.yanis.pk]).update(last_login=timezone.now())

    def setUp(self):
        log_in_verified(self.client, self.front_desk)


class AccessTests(ResidentsTestCase):
    def test_anonymous_redirected_to_login(self):
        self.client.logout()
        response = self.client.get(reverse("residents:list"))
        self.assertEqual(response.status_code, 302)

    def test_without_the_permission(self):
        roles_without_access = [
            ("max", [Role.MAINTENANCE]),
            ("lina", []),
            ("mod", [Role.MODERATOR]),
        ]
        for name, roles in roles_without_access:
            with self.subTest(name=name):
                log_in_verified(self.client, make_user(name, *roles))
                for url in [
                    reverse("residents:list"),
                    reverse("residents:create"),
                    reverse("residents:detail", args=[self.awa.pk]),
                ]:
                    self.assertEqual(self.client.get(url).status_code, 403)

    def test_educator_read_only(self):
        log_in_verified(self.client, make_user("sam", Role.EDUCATOR))
        response = self.client.get(reverse("residents:list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, ">Résidents</a>")
        self.assertNotContains(response, "Nouveau résident")
        self.assertNotContains(response, "Des résidents (CSV ou Excel)")
        self.assertContains(response, 'class="table__link"')
        # Profile: read only, without a form.
        response = self.client.get(reverse("residents:detail", args=[self.awa.pk]))
        save_page("residents-detail-read-only", response)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["form"])
        self.assertNotContains(response, '<form class="card')
        self.assertContains(response, '<a href="tel:+33612345647">06 12 34 56 47</a>', html=True)
        self.assertContains(response, "Chambre 312 · 3e étage")
        # No change, no creation, no import.
        data = {"first_name": "Zed", "last_name": "Koné", "phone": "", "email": ""}
        response = self.client.post(reverse("residents:detail", args=[self.awa.pk]), data)
        self.assertEqual(response.status_code, 403)
        self.awa.refresh_from_db()
        self.assertEqual(self.awa.first_name, "Awa")
        for name in ["create", "import", "import_template"]:
            self.assertEqual(self.client.get(reverse(f"residents:{name}")).status_code, 403)

    def test_front_desk_and_admin(self):
        for user in [self.front_desk, make_user("chef", Role.ADMIN)]:
            log_in_verified(self.client, user)
            self.assertEqual(self.client.get(reverse("residents:list")).status_code, 200)

    def test_link_in_the_menu(self):
        response = self.client.get(reverse("residents:list"))
        self.assertContains(
            response,
            f'<a href="{reverse("residents:list")}" aria-current="page">Résidents</a>',
            html=True,
        )
        # Maintenance has no access to the profiles: no link.
        log_in_verified(self.client, make_user("max", Role.MAINTENANCE))
        response = self.client.get(reverse("ui:guide"))
        self.assertNotContains(response, reverse("residents:list"))

    def test_no_profile_here_for_a_staff_member(self):
        response = self.client.get(reverse("residents:detail", args=[self.front_desk.pk]))
        self.assertEqual(response.status_code, 404)


class ListTests(ResidentsTestCase):
    def usernames(self, response):
        return [r.username for r in response.context["page_obj"]]

    def test_list_and_counts(self):
        response = self.client.get(reverse("residents:list"))
        save_page("residents-list", response)
        # Staff members are not listed; the moderator resident is, with a badge.
        self.assertEqual(self.usernames(response), ["awa.kone", "lucas.p", "yanis.t"])
        self.assertEqual(
            response.context["counts"],
            {"total": 3, "former": 0, "current": 3, "active": 2, "pending": 1, "disabled": 0},
        )
        self.assertContains(response, "3 résidents · 1 compte à activer")
        self.assertContains(response, '<span class="badge badge--neutral">Modérateur</span>')
        self.assertContains(response, "312 · 3e")
        self.assertContains(response, "Sans chambre")

    def test_masked_phone(self):
        response = self.client.get(reverse("residents:list"))
        self.assertContains(response, "06 •• •• •• 47")
        self.assertContains(response, "numéro finissant par 47")
        self.assertNotContains(response, "12 34")
        self.assertNotContains(response, "+33612345647")

    def test_search_by_name_or_room(self):
        cases = {
            "koné": ["awa.kone"],
            "KON": ["awa.kone"],
            "118": ["yanis.t"],
            "lucas petit": ["lucas.p"],
        }
        for search, expected in cases.items():
            with self.subTest(search=search):
                response = self.client.get(reverse("residents:list"), {"q": search})
                self.assertEqual(self.usernames(response), expected)

    def test_filters(self):
        cases = [
            ({"floor": self.f3.pk}, ["awa.kone"]),
            ({"floor": "none"}, ["lucas.p"]),
            ({"account": AccountState.PENDING}, ["lucas.p"]),
            ({"account": AccountState.ACTIVE, "floor": self.f1.pk}, ["yanis.t"]),
            # Unknown values: ignored.
            ({"floor": "999", "account": "pirate"}, ["awa.kone", "lucas.p", "yanis.t"]),
        ]
        for params, expected in cases:
            with self.subTest(params=params):
                response = self.client.get(reverse("residents:list"), params)
                self.assertEqual(self.usernames(response), expected)

    def test_past_stay_does_not_count(self):
        Stay.objects.create(resident=self.lucas, room=self.r304, arrival=D1, departure=D2)
        response = self.client.get(reverse("residents:list"), {"q": "304"})
        self.assertEqual(self.usernames(response), [])

    def test_no_result(self):
        response = self.client.get(reverse("residents:list"), {"q": "zzz"})
        save_page("residents-list-no-result", response)
        self.assertContains(response, "Aucun résident ne correspond à ces critères.")
        self.assertContains(response, "Effacer les filtres")

    def test_pagination_keeps_the_filters(self):
        for i in range(55):
            User.objects.create_user(f"r{i:02}", first_name="Zoé", last_name=f"N{i:02}")
        response = self.client.get(reverse("residents:list"), {"q": "zoé"})
        self.assertContains(response, "?q=zo%C3%A9&amp;page=2")
        response = self.client.get(reverse("residents:list"), {"q": "zoé", "page": 2})
        self.assertEqual(len(response.context["page_obj"]), 5)

    def test_stable_query_count(self):
        url = reverse("residents:list")
        self.client.get(url)
        # Including 3 for the session (saved on each request) and 2 for the passkey
        # that verified the session (django-otp, card T14), 1 for the wifi (T15) and 1
        # for the number of wifi accesses to renew (T17), 1 for the new reports in the
        # menu (T31).
        with self.assertNumQueries(19):
            self.client.get(url)
        for i in range(10):
            resident = User.objects.create_user(f"x{i}", first_name="X", last_name=str(i))
            Stay.objects.create(
                resident=resident,
                room=Room.objects.create(number=f"2{i:02}", floor=self.f1),
                arrival=D1,
            )
        with self.assertNumQueries(19):
            self.client.get(url)


class CreationTests(ResidentsTestCase):
    def data(self, **others):
        return {
            "first_name": "Inès",
            "last_name": "Martin",
            "phone": "07 81 23 45 88",
            "email": "",
            "room": self.r304.pk,
            "arrival": "2026-11-03",
        } | others

    def test_empty_form(self):
        response = self.client.get(reverse("residents:create"))
        save_page("residents-new", response)
        self.assertContains(response, "Nouveau résident")
        # Rooms offered: free ones only.
        rooms = list(response.context["form"].fields["room"].queryset)
        self.assertEqual(rooms, [self.r304])
        self.assertEqual(response.context["form"]["arrival"].value(), timezone.localdate())

    def test_creation(self):
        response = self.client.post(reverse("residents:create"), self.data(), follow=True)
        ines = User.objects.get(first_name="Inès")
        self.assertRedirects(response, reverse("residents:detail", args=[ines.pk]))
        self.assertContains(response, "La fiche de Inès Martin est créée.")
        self.assertEqual(ines.username, "ines.martin")
        self.assertEqual(ines.phone, "+33781234588")
        self.assertFalse(ines.has_usable_password())
        self.assertEqual(ines.roles, set())
        stay = current_stay(ines)
        self.assertEqual((stay.room, stay.arrival), (self.r304, date(2026, 11, 3)))
        save_page("residents-detail-created", response)

    def test_creation_without_room(self):
        self.client.post(reverse("residents:create"), self.data(room="", arrival=""))
        ines = User.objects.get(first_name="Inès")
        self.assertFalse(ines.stays.exists())

    def test_errors_shown_and_linked_to_the_field(self):
        response = self.client.post(
            reverse("residents:create"),
            self.data(first_name="", phone="06 12", room=self.r312.pk),
        )
        save_page("residents-new-errors", response)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(last_name="Martin").exists())
        self.assertContains(response, "La fiche n'est pas enregistrée.")
        self.assertContains(response, 'aria-invalid="true"', count=3)
        self.assertContains(response, 'id="id_phone_error"')
        self.assertContains(response, 'aria-describedby="id_phone_helptext id_phone_error"')
        self.assertContains(response, "Ce numéro n&#x27;existe pas.")
        # 312 is taken: it is not offered.
        self.assertContains(response, "Sélectionnez un choix valide.")

    def test_date_required_with_a_room(self):
        response = self.client.post(reverse("residents:create"), self.data(arrival=""))
        self.assertFormError(
            response.context["form"], "arrival", "Indiquez la date d'arrivée dans la chambre."
        )

    def test_number_already_taken(self):
        response = self.client.post(reverse("residents:create"), self.data(phone="06 12 34 56 47"))
        self.assertFormError(
            response.context["form"],
            None,
            "Ce numéro est déjà utilisé par une autre personne.",
        )

    def test_free_username(self):
        self.assertEqual(free_username("Awa", "Koné"), "awa.kone-2")
        User.objects.create_user("awa.kone-2")
        self.assertEqual(free_username("Awa", "Koné"), "awa.kone-3")
        self.assertEqual(free_username("", "!!"), "resident")


class DetailTests(ResidentsTestCase):
    def url(self, resident=None):
        return reverse("residents:detail", args=[(resident or self.awa).pk])

    def data(self, **others):
        return {
            "first_name": "Awa",
            "last_name": "Koné",
            "phone": "+33612345647",
            "email": "",
            "room": self.r312.pk,
            "arrival": "2026-09-01",
        } | others

    def test_display(self):
        Stay.objects.create(resident=self.lucas, room=self.r304, arrival=D1, departure=D2)
        response = self.client.get(self.url(self.lucas))
        save_page("residents-detail", response)
        self.assertContains(response, "<h1>Lucas Petit</h1>", html=True)
        self.assertContains(response, "Pas encore activé")
        self.assertContains(response, "Du <time")
        response = self.client.get(self.url())
        # On the profile, the number is complete; the current room is selected.
        self.assertContains(response, "06 12 34 56 47")
        form = response.context["form"]
        self.assertEqual(form["room"].value(), self.r312.pk)
        self.assertEqual(list(form.fields["room"].queryset), [self.r304, self.r312])
        self.assertIsNone(form.fields["room"].empty_label)

    def test_change(self):
        response = self.client.post(self.url(), self.data(last_name="Koné-Diallo"))
        self.assertRedirects(response, self.url())
        self.awa.refresh_from_db()
        self.assertEqual(self.awa.last_name, "Koné-Diallo")
        self.assertEqual(self.awa.username, "awa.kone")
        self.assertEqual(self.awa.stays.count(), 1)

    def test_move_inside_the_residence(self):
        self.client.post(self.url(), self.data(room=self.r304.pk, arrival="2026-11-02"))
        old, new = self.awa.stays.order_by("arrival")
        self.assertEqual((old.room, old.departure), (self.r312, date(2026, 11, 2)))
        self.assertEqual((new.room, new.departure), (self.r304, None))

    def test_fix_the_arrival_date(self):
        self.client.post(self.url(), self.data(arrival="2026-08-28"))
        self.assertEqual(current_stay(self.awa).arrival, date(2026, 8, 28))

    def test_move_before_the_arrival_refused(self):
        response = self.client.post(self.url(), self.data(room=self.r304.pk, arrival="2026-08-01"))
        self.assertFormError(
            response.context["form"],
            "arrival",
            "Pour un déménagement, indiquez sa date : après le 01/09/2026, "
            "jour d'arrivée dans la chambre actuelle.",
        )
        self.assertEqual(current_stay(self.awa).room, self.r312)
        self.assertContains(response, "<h1>Awa Koné</h1>", html=True)

    def test_change_room_without_changing_the_date_refused(self):
        # The date offered is the one of the current stay: forgetting it must not
        # erase the old room from the history.
        response = self.client.post(self.url(), self.data(room=self.r304.pk))
        self.assertIn("arrival", response.context["form"].errors)
        self.assertEqual(current_stay(self.awa).room, self.r312)
        self.assertEqual(self.awa.stays.count(), 1)

    def test_fix_the_room_on_the_arrival_day(self):
        today = timezone.localdate()
        self.client.post(
            reverse("residents:create"),
            {
                "first_name": "Léa",
                "last_name": "Moreau",
                "phone": "",
                "email": "",
                "room": self.r304.pk,
                "arrival": today.isoformat(),
            },
        )
        lea = User.objects.get(first_name="Léa")
        r305 = Room.objects.create(number="305", floor=self.f3)
        self.client.post(
            self.url(lea),
            {
                "first_name": "Léa",
                "last_name": "Moreau",
                "phone": "",
                "email": "",
                "room": r305.pk,
                "arrival": today.isoformat(),
            },
        )
        self.assertEqual(lea.stays.get().room, r305)

    def test_room_taken_at_the_same_moment(self):
        # Simulate the race: the database constraint refuses the second stay.
        from unittest import mock

        from django.db import IntegrityError

        with mock.patch("residents.forms.assign_room", side_effect=IntegrityError("unique")):
            response = self.client.post(
                self.url(), self.data(room=self.r304.pk, arrival="2026-11-02")
            )
        self.assertFormError(
            response.context["form"],
            "room",
            "Cette chambre vient d'être attribuée. Choisissez-en une autre.",
        )
        self.awa.refresh_from_db()
        self.assertEqual(current_stay(self.awa).room, self.r312)

    def test_room_required_during_a_stay(self):
        response = self.client.post(self.url(), self.data(room=""))
        self.assertFormError(response.context["form"], "room", "Ce champ est obligatoire.")

    def test_names_unchanged_if_the_profile_is_refused(self):
        response = self.client.post(self.url(), self.data(first_name="Zed", phone="06"))
        self.assertContains(response, "<h1>Awa Koné</h1>", html=True)
        self.awa.refresh_from_db()
        self.assertEqual(self.awa.first_name, "Awa")


class ModelTests(TestCase):
    def test_residents_excludes_staff(self):
        make_user("lina")
        make_user("yanis", Role.MODERATOR)
        make_user("sam", Role.EDUCATOR, Role.MODERATOR)
        make_user("nadia", Role.FRONT_DESK)
        self.assertQuerySetEqual(
            User.objects.residents().order_by("username"),
            ["lina", "yanis"],
            transform=lambda u: u.username,
        )

    def test_account_state(self):
        lina = make_user("lina")
        self.assertEqual(lina.account_state, AccountState.PENDING)
        lina.last_login = timezone.now() - timedelta(days=1)
        self.assertEqual(lina.account_state, AccountState.ACTIVE)
        lina.is_active = False
        self.assertEqual(lina.account_state, AccountState.DISABLED)


class DesignTests(ResidentsTestCase):
    """The resident page after the design audit (card D3)."""

    def test_actions_first_contact_for_everyone(self):
        log_in_verified(self.client, self.front_desk)
        url = reverse("residents:detail", args=[self.awa.pk])
        response = self.client.get(url)
        page = response.content.decode()
        self.assertIn('href="tel:+33612345647"', page)  # without opening the form
        self.assertLess(page.index("activation-title"), page.index('id="edit"'))
        self.assertNotIn("Identifiant interne", page)  # front desk: not needed
        # Errors: the form opens and a link at the top leads to it.
        response = self.client.post(url, {"first_name": "", "last_name": "Koné"})
        self.assertContains(response, 'id="edit" open')
        self.assertContains(response, '<a href="#edit">Voir les champs à corriger</a>')
