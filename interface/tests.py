from django.contrib.staticfiles import finders
from django.template import Context, Template
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from comptes.models import User
from outils.capture_html import enregistrer_page


class GuideDeStyleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.equipe = User.objects.create_user(
            username="equipe", password="mot-de-passe-de-test", is_staff=True
        )
        cls.resident = User.objects.create_user(
            username="resident", password="mot-de-passe-de-test"
        )

    def test_reserve_a_l_equipe(self):
        url = reverse("interface:guide")
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.resident)
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_guide_de_style(self):
        self.client.force_login(self.equipe)
        reponse = self.client.get(reverse("interface:guide"))
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, '<html lang="fr">')
        self.assertContains(reponse, 'href="#contenu"')
        self.assertContains(reponse, "interface/css/hjb.css")
        enregistrer_page("guide-de-style", reponse)

    def test_accueil_resident_d_exemple(self):
        self.client.force_login(self.equipe)
        reponse = self.client.get(reverse("interface:guide-resident"))
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, 'aria-label="Navigation principale"')
        # L'entrée active de la barre du bas est signalée aux lecteurs d'écran.
        self.assertContains(reponse, 'aria-current="page"', count=1)
        enregistrer_page("guide-accueil-resident", reponse)


class IconesTests(SimpleTestCase):
    def rendre(self, texte, **contexte):
        return Template("{% load icones %}" + texte).render(Context(contexte))

    def test_icone_decorative_cachee_aux_lecteurs_d_ecran(self):
        html = self.rendre('{% icone "maison" %}')
        self.assertIn('aria-hidden="true"', html)
        self.assertNotIn("role=", html)

    def test_icone_nommee(self):
        html = self.rendre('{% icone "cloche" etiquette="Notifications" %}')
        self.assertIn('role="img"', html)
        self.assertIn('aria-label="Notifications"', html)

    def test_etiquette_venant_d_une_variable_est_echappee(self):
        # Les données (noms, saisies) arrivent par des variables : elles sont échappées.
        html = self.rendre('{% icone "cloche" etiquette=nom %}', nom='Awa "<script>')
        self.assertIn('aria-label="Awa &quot;&lt;script&gt;"', html)

    def test_icone_inconnue(self):
        with self.assertRaises(KeyError):
            self.rendre('{% icone "inexistante" %}')


class FichiersStatiquesTests(SimpleTestCase):
    def test_feuille_de_style_et_polices_presentes(self):
        for chemin in (
            "interface/css/hjb.css",
            "interface/fonts/bricolage-grotesque-latin-wght-normal.woff2",
            "interface/fonts/atkinson-hyperlegible-latin-400-normal.woff2",
            "interface/fonts/atkinson-hyperlegible-latin-700-normal.woff2",
            "interface/fonts/OFL-bricolage-grotesque.txt",
            "interface/fonts/OFL-atkinson-hyperlegible.txt",
        ):
            with self.subTest(chemin=chemin):
                self.assertIsNotNone(finders.find(chemin))
