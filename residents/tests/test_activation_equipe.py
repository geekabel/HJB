"""Code d'activation et retour d'un ancien résident, côté équipe (carte T11)."""

from datetime import date

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from comptes.activation import utiliser_code
from comptes.models import CodeActivation
from comptes.roles import Role
from comptes.tests.outils import creer_utilisateur
from journal.models import Action, EntreeJournal
from logement.models import Chambre, Etage, Sejour
from logement.services import sejour_en_cours
from outils.capture_html import enregistrer_page
from residents.depart import enregistrer_depart
from sms.fournisseurs import memoire

from .test_import import csv_


class EquipeTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.accueil = creer_utilisateur("nadia", Role.ACCUEIL, first_name="Nadia", last_name="B.")
        e3 = Etage.objects.create(numero=3)
        cls.c312 = Chambre.objects.create(numero="312", etage=e3)
        cls.c304 = Chambre.objects.create(numero="304", etage=e3)
        cls.awa = creer_utilisateur(
            "awa.kone", first_name="Awa", last_name="Koné", telephone="+33612345647"
        )
        Sejour.objects.create(resident=cls.awa, chambre=cls.c312, arrivee=date(2026, 9, 1))

    def setUp(self):
        self.client.force_login(self.accueil)

    def url_code(self, resident=None):
        return reverse("residents:code_activation", args=[(resident or self.awa).pk])

    def jeton(self, resident=None):
        """Jeton du bouton « Générer », tel que la fiche le donne."""
        reponse = self.client.get(reverse("residents:fiche", args=[(resident or self.awa).pk]))
        return reponse.context["jeton_code"]

    def generer(self, resident=None, **kwargs):
        return self.client.post(self.url_code(resident), {"jeton": self.jeton(resident)}, **kwargs)


class CodeActivationTests(EquipeTestCase):
    def test_section_de_la_fiche(self):
        reponse = self.client.get(reverse("residents:fiche", args=[self.awa.pk]))
        self.assertContains(reponse, "Aucun code remis pour l'instant.")
        self.assertContains(reponse, f'action="{self.url_code()}"')

    def test_generation_et_feuille_imprimable(self):
        reponse = self.generer()
        enregistrer_page("residents-code-activation", reponse)
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("no-store", reponse["Cache-Control"])
        code = reponse.context["code"]
        self.assertContains(reponse, f'<p class="feuille-code__code">{code}</p>', html=True)
        self.assertContains(reponse, "http://testserver/activer/")
        self.assertContains(reponse, "<svg")
        self.assertContains(reponse, "Ce code ne s'affichera qu'une fois.")
        # Le code n'est gardé en clair nulle part, pas même dans la session.
        from django.contrib.sessions.models import Session

        for session in Session.objects.all():
            self.assertNotIn(code, str(session.get_decoded()))
        # Le code marche bien, une fois.
        self.assertEqual(utiliser_code(code, "192.0.2.1").utilisateur, self.awa)
        entree = EntreeJournal.objects.get(action=Action.CODE_ACTIVATION_GENERE)
        self.assertEqual(entree.acteur, self.accueil)
        # La fiche montre l'état sans jamais réafficher le code.
        reponse = self.client.get(reverse("residents:fiche", args=[self.awa.pk]))
        self.assertContains(reponse, "Dernier code utilisé le")
        self.assertNotContains(reponse, code)

    def test_renvoyer_le_formulaire_ne_change_pas_le_code(self):
        jeton = self.jeton()
        self.client.post(self.url_code(), {"jeton": jeton})
        empreinte_remise = CodeActivation.objects.get().empreinte
        # Rechargement de la page : le même formulaire repart.
        reponse = self.client.post(self.url_code(), {"jeton": jeton}, follow=True)
        self.assertRedirects(reponse, reverse("residents:fiche", args=[self.awa.pk]))
        self.assertContains(reponse, "Ce code a déjà été généré : il reste valable.")
        self.assertEqual(
            list(CodeActivation.objects.valides().values_list("empreinte", flat=True)),
            [empreinte_remise],
        )

    def test_sans_jeton_ou_jeton_d_un_autre_resident(self):
        lina = creer_utilisateur("lina")
        self.assertEqual(self.client.post(self.url_code()).status_code, 302)
        jeton_lina = self.jeton(lina)
        self.assertEqual(self.client.post(self.url_code(), {"jeton": jeton_lina}).status_code, 302)
        self.assertFalse(CodeActivation.objects.exists())

    def test_deux_onglets(self):
        jeton_1, jeton_2 = self.jeton(), self.jeton()
        self.assertEqual(self.client.post(self.url_code(), {"jeton": jeton_1}).status_code, 200)
        self.assertEqual(self.client.post(self.url_code(), {"jeton": jeton_2}).status_code, 200)
        self.assertEqual(CodeActivation.objects.valides().count(), 1)  # le second remplace

    def test_code_en_attente_sur_la_fiche(self):
        self.generer()
        reponse = self.client.get(reverse("residents:fiche", args=[self.awa.pk]))
        self.assertContains(reponse, "Code en attente")
        self.assertContains(reponse, "remis par Nadia B.")
        self.assertContains(reponse, "Générer un nouveau code")

    def test_cle_d_acces_sur_la_fiche(self):
        """Carte T13 : l'accueil voit si l'activation est allée jusqu'à la clé."""
        from connexion.tests.authentificateur import Authentificateur

        url = reverse("residents:fiche", args=[self.awa.pk])
        self.generer()
        CodeActivation.objects.update(utilise_le=timezone.now())  # code saisi, puis abandon
        self.assertContains(self.client.get(url), "pas allée jusqu'au bout")

        Authentificateur().enregistrer(self.awa)
        reponse = self.client.get(url)
        self.assertNotContains(reponse, "pas allée jusqu")
        self.assertContains(reponse, "Clé d'accès créée le <time")

    def test_jamais_en_get(self):
        self.assertEqual(self.client.get(self.url_code()).status_code, 405)

    def test_reserve(self):
        for roles in ([Role.EDUCATEUR], [Role.MAINTENANCE], []):
            self.client.force_login(creer_utilisateur(f"u{len(roles)}{roles}", *roles))
            self.assertEqual(self.client.post(self.url_code()).status_code, 403)
        self.client.force_login(creer_utilisateur("sam", Role.EDUCATEUR))
        reponse = self.client.get(reverse("residents:fiche", args=[self.awa.pk]))
        self.assertNotContains(reponse, "Activation du compte")
        self.assertFalse(CodeActivation.objects.exists())

    def test_pas_pour_un_compte_desactive(self):
        jeton = self.jeton()
        enregistrer_depart(self.awa, timezone.localdate())
        reponse = self.client.post(self.url_code(), {"jeton": jeton}, follow=True)
        self.assertContains(reponse, "enregistrez d&#x27;abord le retour")
        self.assertFalse(CodeActivation.objects.exists())

    def test_le_depart_annule_le_code(self):
        self.generer()
        enregistrer_depart(self.awa, timezone.localdate())
        self.assertFalse(CodeActivation.objects.valides().exists())


class RetourTests(EquipeTestCase):
    def setUp(self):
        super().setUp()
        enregistrer_depart(self.awa, timezone.localdate())
        self.url = reverse("residents:retour", args=[self.awa.pk])

    def test_retour(self):
        reponse = self.client.get(self.url)
        enregistrer_page("residents-retour", reponse)
        self.assertContains(reponse, "Retour de Awa Koné")
        reponse = self.client.post(
            self.url,
            {"chambre": self.c304.pk, "arrivee": timezone.localdate().isoformat()},
            follow=True,
        )
        self.assertContains(reponse, "Le retour est enregistré et le compte réactivé.")
        self.awa.refresh_from_db()
        self.assertTrue(self.awa.is_active)
        self.assertEqual(sejour_en_cours(self.awa).chambre, self.c304)
        entree = EntreeJournal.objects.get(action=Action.RETOUR_RESIDENT)
        self.assertEqual(
            entree.resume(), f"Chambre 304, retour le {timezone.localdate():%d/%m/%Y}."
        )
        # L'ancienne connexion ne fait pas passer le compte pour activé.
        self.assertIsNone(self.awa.last_login)
        self.assertEqual(self.awa.etat_compte, "en_attente")
        # Ensuite, un code peut être généré.
        self.assertEqual(self.generer().status_code, 200)
        self.assertTrue(CodeActivation.objects.valides().exists())

    def test_lien_depuis_la_fiche(self):
        reponse = self.client.get(reverse("residents:fiche", args=[self.awa.pk]))
        self.assertContains(reponse, f'href="{self.url}"')

    def test_lien_visible_sans_le_droit_de_generer_des_codes(self):
        from django.contrib.auth.models import Permission

        # Maintenance, plus la gestion des résidents donnée à la main : pas de droit
        # sur les codes d'activation.
        gestion = creer_utilisateur("gestion", Role.MAINTENANCE)
        gestion.user_permissions.set(
            Permission.objects.filter(codename__in=["voir_residents", "gerer_residents"])
        )
        self.client.force_login(gestion)
        reponse = self.client.get(reverse("residents:fiche", args=[self.awa.pk]))
        self.assertContains(reponse, f'href="{self.url}"')
        self.assertNotContains(reponse, "Activation du compte")

    def test_pas_pour_un_resident_actuel(self):
        lina = creer_utilisateur("lina")
        reponse = self.client.get(reverse("residents:retour", args=[lina.pk]))
        self.assertRedirects(reponse, reverse("residents:fiche", args=[lina.pk]))

    def test_reserve_a_la_gestion(self):
        self.client.force_login(creer_utilisateur("sam", Role.EDUCATEUR))
        self.assertEqual(self.client.get(self.url).status_code, 403)


class ImportAvecCodesTests(EquipeTestCase):
    def setUp(self):
        super().setUp()
        memoire.boite.clear()

    def importer(self, envoyer_codes):
        self.client.post(
            reverse("residents:import"),
            {"fichier": csv_("Prénom;Nom;Téléphone\nInès;Martin;07 81 23 45 88\nLéa;Moreau;\n")},
        )
        jeton = self.client.session["import_residents"]["jeton"]
        donnees = {"action": "importer", "pretes": "2,3", "jeton": jeton}
        if envoyer_codes:
            donnees["envoyer_codes"] = "oui"
        return self.client.post(reverse("residents:import_apercu"), donnees, follow=True)

    def test_option_visible(self):
        self.client.post(
            reverse("residents:import"), {"fichier": csv_("Prénom;Nom\nInès;Martin\n")}
        )
        reponse = self.client.get(reverse("residents:import_apercu"))
        self.assertContains(reponse, 'name="envoyer_codes"')

    def test_sans_l_option(self):
        self.importer(envoyer_codes=False)
        self.assertEqual(memoire.boite, [])
        self.assertFalse(CodeActivation.objects.exists())

    def test_une_panne_imprevue_ne_casse_pas_l_import(self):
        from unittest import mock

        with (
            mock.patch("residents.views.envoyer_code_par_sms", side_effect=RuntimeError("panne")),
            self.assertLogs("residents.views", "ERROR"),
        ):
            reponse = self.importer(envoyer_codes=True)
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "2 résidents importés.")
        self.assertContains(reponse, "1 SMS n&#x27;ont pas pu partir")

    def test_trop_de_codes_a_envoyer(self):
        from unittest import mock

        with mock.patch("residents.views.CODES_SMS_MAX", 0):
            reponse = self.importer(envoyer_codes=True)
        self.assertContains(reponse, "aucun SMS n&#x27;est parti")
        self.assertEqual(memoire.boite, [])

    def test_avec_l_option(self):
        reponse = self.importer(envoyer_codes=True)
        self.assertContains(reponse, "2 résidents importés.")
        self.assertContains(reponse, "1 code d&#x27;activation envoyé par SMS.")
        self.assertContains(reponse, "1 résident(s) sans numéro")
        (sms,) = memoire.boite
        self.assertEqual(sms.numero, "+33781234588")
        self.assertEqual(CodeActivation.objects.valides().count(), 1)
