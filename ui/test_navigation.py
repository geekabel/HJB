"""Navigation of both areas, account page, error pages (design card D1)."""

from django.test import TestCase
from django.urls import reverse

from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user
from tools.html_capture import save_page


class ResidentNavigationTests(TestCase):
    def setUp(self):
        self.ines = make_user("ines", first_name="Inès")
        log_in_verified(self.client, self.ines)

    def test_four_real_tabs_and_no_dead_link(self):
        response = self.client.get(reverse("home"))
        save_page("home-resident-d1", response)
        nav = response.content.decode().split('class="resident-nav"')[1]
        self.assertEqual(nav.count("<li>"), 4)
        self.assertNotIn('href="#"', response.content.decode())
        # The brand shows on the home page only.
        self.assertContains(response, "resident-page__header")
        response = self.client.get(reverse("inbox:list"))
        self.assertNotContains(response, "resident-page__header")
        self.assertNotContains(response, "Retour à l&#x27;accueil")  # a tab has no back arrow

    def test_account_page(self):
        response = self.client.get(reverse("account"))
        save_page("account-resident-empty", response)
        self.assertContains(response, '<a href="/compte/" aria-current="page">')
        self.assertContains(response, "Pas encore activées")
        self.assertContains(response, 'action="/connexion/deconnexion/"')


class StaffNavigationTests(TestCase):
    def test_menu_has_logout_and_no_dead_link(self):
        log_in_verified(self.client, make_user("karim", Role.FRONT_DESK, first_name="Karim"))
        response = self.client.get(reverse("residents:list"))
        page = response.content.decode()
        self.assertNotIn('href="#"', page)
        self.assertIn("Se déconnecter", page)
        self.assertIn("data-menu-toggle hidden", page)  # shown by app.js only
        self.assertNotIn("Discussions", page)  # not an educator
        response = self.client.get(reverse("account"))
        save_page("account-staff", response)
        self.assertContains(response, "staff-menu")

    def test_each_role_starts_on_its_main_page(self):
        samia = make_user("samia", Role.EDUCATOR)
        log_in_verified(self.client, samia)
        self.assertRedirects(
            self.client.get(reverse("home")),
            reverse("appointments:availability"),
            fetch_redirect_response=False,
        )
        response = self.client.get(reverse("appointments:conversations"))
        self.assertContains(response, 'aria-current="page">Discussions')
        log_in_verified(self.client, make_user("karim", Role.FRONT_DESK))
        self.assertRedirects(
            self.client.get(reverse("home")),
            reverse("residents:list"),
            fetch_redirect_response=False,
        )
        log_in_verified(self.client, make_user("marie", Role.ADMIN))
        self.assertRedirects(
            self.client.get(reverse("home")),
            reverse("residents:list"),
            fetch_redirect_response=False,
        )
        # Maintenance never gets the resident home (it looped on its tabs).
        log_in_verified(self.client, make_user("marc", Role.MAINTENANCE))
        response = self.client.get(reverse("home"), follow=True)
        self.assertContains(response, "staff-menu")
        self.assertNotContains(response, "resident-nav")
        self.assertNotContains(response, "Mon wifi")

    def test_superuser_without_roles_is_not_called_resident(self):
        root = make_user("root", is_staff=True, is_superuser=True)
        self.assertEqual(root.roles_label, "Équipe")


class ErrorPageTests(TestCase):
    def test_404_and_403_look_like_the_app(self):
        response = self.client.get("/nulle-part/")
        self.assertEqual(response.status_code, 404)
        save_page("error-404", response)
        self.assertContains(response, "Page introuvable", status_code=404)
        self.assertContains(response, "Retour à l'accueil", status_code=404)
        log_in_verified(self.client, make_user("ines"))
        response = self.client.get(reverse("residents:list"))
        self.assertContains(response, "Accès refusé", status_code=403)

    def test_500_renders_without_context(self):
        from django.template.loader import render_to_string

        html = render_to_string("500.html")
        self.assertIn("Un problème est survenu", html)
