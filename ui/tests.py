from django.contrib.staticfiles import finders
from django.template import Context, Template
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user
from tools.html_capture import save_page


class StyleGuideTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = make_user("staff", Role.FRONT_DESK)
        cls.resident = make_user("resident")
        # A resident with the moderator role has no access to the staff area.
        cls.moderator = make_user("moderator", Role.MODERATOR)

    def test_staff_only(self):
        url = reverse("ui:guide")
        # Anonymous: sent to the login page.
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("access:login"), response["Location"])
        # Logged-in resident, moderator or not: access denied, with no login loop.
        for account in (self.resident, self.moderator):
            with self.subTest(account=account.username):
                log_in_verified(self.client, account)
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_style_guide(self):
        log_in_verified(self.client, self.staff)
        response = self.client.get(reverse("ui:guide"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<html lang="fr">')
        self.assertContains(response, 'href="#content"')
        self.assertContains(response, "ui/css/hjb.css")
        save_page("style-guide", response)

    def test_sample_resident_home(self):
        log_in_verified(self.client, self.staff)
        response = self.client.get(reverse("ui:guide_resident"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-label="Navigation principale"')
        # The active entry of the bottom bar is announced to screen readers.
        self.assertContains(response, 'aria-current="page"', count=1)
        save_page("guide-resident-home", response)


class IconsTests(SimpleTestCase):
    def render(self, text, **context):
        return Template("{% load icons %}" + text).render(Context(context))

    def test_decorative_icon_hidden_from_screen_readers(self):
        html = self.render('{% icon "home" %}')
        self.assertIn('aria-hidden="true"', html)
        self.assertNotIn("role=", html)

    def test_named_icon(self):
        html = self.render('{% icon "bell" label="Notifications" %}')
        self.assertIn('role="img"', html)
        self.assertIn('aria-label="Notifications"', html)

    def test_label_from_a_variable_is_escaped(self):
        # Data (names, user input) comes through variables: it is escaped.
        html = self.render('{% icon "bell" label=name %}', name='Awa "<script>')
        self.assertIn('aria-label="Awa &quot;&lt;script&gt;"', html)

    def test_unknown_icon(self):
        with self.assertRaises(KeyError):
            self.render('{% icon "missing" %}')


class StaticFilesTests(SimpleTestCase):
    def test_stylesheet_and_fonts_present(self):
        for path in (
            "ui/css/hjb.css",
            "ui/fonts/bricolage-grotesque-latin-wght-normal.woff2",
            "ui/fonts/atkinson-hyperlegible-latin-400-normal.woff2",
            "ui/fonts/atkinson-hyperlegible-latin-700-normal.woff2",
            "ui/fonts/OFL-bricolage-grotesque.txt",
            "ui/fonts/OFL-atkinson-hyperlegible.txt",
        ):
            with self.subTest(path=path):
                self.assertIsNotNone(finders.find(path))
