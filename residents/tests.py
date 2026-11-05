from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from comptes.models import EtatCompte, User
from comptes.roles import Role
from comptes.tests.outils import creer_utilisateur
from logement.models import Chambre, Etage, Sejour
from logement.services import sejour_en_cours
from outils.capture_html import enregistrer_page

from .forms import nom_utilisateur_libre

J1 = date(2026, 9, 1)
J2 = date(2026, 10, 15)


class ResidentsTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.accueil = creer_utilisateur("nadia", Role.ACCUEIL, first_name="Nadia", last_name="B.")
        cls.e1 = Etage.objects.create(numero=1)
        cls.e3 = Etage.objects.create(numero=3)
        cls.c118 = Chambre.objects.create(numero="118", etage=cls.e1)
        cls.c304 = Chambre.objects.create(numero="304", etage=cls.e3)
        cls.c312 = Chambre.objects.create(numero="312", etage=cls.e3)
        cls.awa = creer_utilisateur(
            "awa.kone", first_name="Awa", last_name="Koné", telephone="+33612345647"
        )
        cls.yanis = creer_utilisateur(
            "yanis.t", Role.MODERATEUR, first_name="Yanis", last_name="Traoré"
        )
        cls.lucas = creer_utilisateur("lucas.p", first_name="Lucas", last_name="Petit")
        Sejour.objects.create(resident=cls.awa, chambre=cls.c312, arrivee=J1)
        Sejour.objects.create(resident=cls.yanis, chambre=cls.c118, arrivee=J1)
        # Awa et Yanis se sont déjà connectés ; Lucas pas encore.
        User.objects.filter(pk__in=[cls.awa.pk, cls.yanis.pk]).update(last_login=timezone.now())

    def setUp(self):
        self.client.force_login(self.accueil)


class AccesTests(ResidentsTestCase):
    def test_anonyme_renvoye_vers_la_connexion(self):
        self.client.logout()
        reponse = self.client.get(reverse("residents:liste"))
        self.assertEqual(reponse.status_code, 302)

    def test_sans_la_permission(self):
        for nom, roles in [("sam", [Role.EDUCATEUR]), ("lina", []), ("mod", [Role.MODERATEUR])]:
            with self.subTest(nom=nom):
                self.client.force_login(creer_utilisateur(nom, *roles))
                for url in [
                    reverse("residents:liste"),
                    reverse("residents:creer"),
                    reverse("residents:fiche", args=[self.awa.pk]),
                ]:
                    self.assertEqual(self.client.get(url).status_code, 403)

    def test_accueil_et_administration(self):
        for utilisateur in [self.accueil, creer_utilisateur("chef", Role.ADMIN)]:
            self.client.force_login(utilisateur)
            self.assertEqual(self.client.get(reverse("residents:liste")).status_code, 200)

    def test_lien_dans_le_menu(self):
        reponse = self.client.get(reverse("residents:liste"))
        self.assertContains(
            reponse,
            f'<a href="{reverse("residents:liste")}" aria-current="page">Résidents et wifi</a>',
            html=True,
        )
        self.client.force_login(creer_utilisateur("sam", Role.EDUCATEUR))
        reponse = self.client.get(reverse("interface:guide"))
        self.assertNotContains(reponse, reverse("residents:liste"))

    def test_la_fiche_d_un_membre_de_l_equipe_n_existe_pas_ici(self):
        reponse = self.client.get(reverse("residents:fiche", args=[self.accueil.pk]))
        self.assertEqual(reponse.status_code, 404)


class ListeTests(ResidentsTestCase):
    def noms(self, reponse):
        return [r.username for r in reponse.context["page_obj"]]

    def test_liste_et_compteurs(self):
        reponse = self.client.get(reverse("residents:liste"))
        enregistrer_page("residents-liste", reponse)
        # L'équipe n'apparaît pas ; le résident modérateur oui, avec son badge.
        self.assertEqual(self.noms(reponse), ["awa.kone", "lucas.p", "yanis.t"])
        self.assertEqual(
            reponse.context["compteurs"],
            {"total": 3, "active": 2, "en_attente": 1, "desactive": 0},
        )
        self.assertContains(reponse, "3 résidents · 2 comptes activés · 1 pas encore activé")
        self.assertContains(reponse, '<span class="badge badge--neutre">Modérateur</span>')
        self.assertContains(reponse, "312 · 3e")
        self.assertContains(reponse, "Sans chambre")

    def test_telephone_masque(self):
        reponse = self.client.get(reverse("residents:liste"))
        self.assertContains(reponse, "06 •• •• •• 47")
        self.assertContains(reponse, "numéro finissant par 47")
        self.assertNotContains(reponse, "12 34")
        self.assertNotContains(reponse, "+33612345647")

    def test_recherche_par_nom_ou_chambre(self):
        cas = {
            "koné": ["awa.kone"],
            "KON": ["awa.kone"],
            "118": ["yanis.t"],
            "lucas petit": ["lucas.p"],
        }
        for recherche, attendus in cas.items():
            with self.subTest(recherche=recherche):
                reponse = self.client.get(reverse("residents:liste"), {"q": recherche})
                self.assertEqual(self.noms(reponse), attendus)

    def test_filtres(self):
        cas = [
            ({"etage": self.e3.pk}, ["awa.kone"]),
            ({"etage": "sans"}, ["lucas.p"]),
            ({"compte": EtatCompte.EN_ATTENTE}, ["lucas.p"]),
            ({"compte": EtatCompte.ACTIVE, "etage": self.e1.pk}, ["yanis.t"]),
            # Valeurs inconnues : ignorées.
            ({"etage": "999", "compte": "pirate"}, ["awa.kone", "lucas.p", "yanis.t"]),
        ]
        for parametres, attendus in cas:
            with self.subTest(parametres=parametres):
                reponse = self.client.get(reverse("residents:liste"), parametres)
                self.assertEqual(self.noms(reponse), attendus)

    def test_ancien_sejour_ne_compte_pas(self):
        Sejour.objects.create(resident=self.lucas, chambre=self.c304, arrivee=J1, depart=J2)
        reponse = self.client.get(reverse("residents:liste"), {"q": "304"})
        self.assertEqual(self.noms(reponse), [])

    def test_aucun_resultat(self):
        reponse = self.client.get(reverse("residents:liste"), {"q": "zzz"})
        enregistrer_page("residents-liste-aucun-resultat", reponse)
        self.assertContains(reponse, "Aucun résident ne correspond à ces critères.")
        self.assertContains(reponse, "Effacer les filtres")

    def test_pagination_garde_les_filtres(self):
        for i in range(55):
            User.objects.create_user(f"r{i:02}", first_name="Zoé", last_name=f"N{i:02}")
        reponse = self.client.get(reverse("residents:liste"), {"q": "zoé"})
        self.assertContains(reponse, "?q=zo%C3%A9&amp;page=2")
        reponse = self.client.get(reverse("residents:liste"), {"q": "zoé", "page": 2})
        self.assertEqual(len(reponse.context["page_obj"]), 5)

    def test_nombre_de_requetes_stable(self):
        url = reverse("residents:liste")
        self.client.get(url)
        with self.assertNumQueries(11):
            self.client.get(url)
        for i in range(10):
            resident = User.objects.create_user(f"x{i}", first_name="X", last_name=str(i))
            Sejour.objects.create(
                resident=resident,
                chambre=Chambre.objects.create(numero=f"2{i:02}", etage=self.e1),
                arrivee=J1,
            )
        with self.assertNumQueries(11):
            self.client.get(url)


class CreationTests(ResidentsTestCase):
    def donnees(self, **autres):
        return {
            "first_name": "Inès",
            "last_name": "Martin",
            "telephone": "07 81 23 45 88",
            "email": "",
            "chambre": self.c304.pk,
            "arrivee": "2026-11-03",
        } | autres

    def test_formulaire_vide(self):
        reponse = self.client.get(reverse("residents:creer"))
        enregistrer_page("residents-nouveau", reponse)
        self.assertContains(reponse, "Nouveau résident")
        # Chambres proposées : les libres seulement.
        chambres = list(reponse.context["formulaire"].fields["chambre"].queryset)
        self.assertEqual(chambres, [self.c304])
        self.assertEqual(reponse.context["formulaire"]["arrivee"].value(), timezone.localdate())

    def test_creation(self):
        reponse = self.client.post(reverse("residents:creer"), self.donnees(), follow=True)
        ines = User.objects.get(first_name="Inès")
        self.assertRedirects(reponse, reverse("residents:fiche", args=[ines.pk]))
        self.assertContains(reponse, "La fiche de Inès Martin est créée.")
        self.assertEqual(ines.username, "ines.martin")
        self.assertEqual(ines.telephone, "+33781234588")
        self.assertFalse(ines.has_usable_password())
        self.assertEqual(ines.roles, set())
        sejour = sejour_en_cours(ines)
        self.assertEqual((sejour.chambre, sejour.arrivee), (self.c304, date(2026, 11, 3)))
        enregistrer_page("residents-fiche-creee", reponse)

    def test_creation_sans_chambre(self):
        self.client.post(reverse("residents:creer"), self.donnees(chambre="", arrivee=""))
        ines = User.objects.get(first_name="Inès")
        self.assertFalse(ines.sejours.exists())

    def test_erreurs_affichees_et_reliees_au_champ(self):
        reponse = self.client.post(
            reverse("residents:creer"),
            self.donnees(first_name="", telephone="06 12", chambre=self.c312.pk),
        )
        enregistrer_page("residents-nouveau-erreurs", reponse)
        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(User.objects.filter(last_name="Martin").exists())
        self.assertContains(reponse, "La fiche n'est pas enregistrée.")
        self.assertContains(reponse, 'aria-invalid="true"', count=3)
        self.assertContains(reponse, 'id="id_telephone_error"')
        self.assertContains(reponse, 'aria-describedby="id_telephone_helptext id_telephone_error"')
        self.assertContains(reponse, "Ce numéro n&#x27;existe pas.")
        # 312 est occupée : elle n'est pas proposée.
        self.assertContains(reponse, "Sélectionnez un choix valide.")

    def test_date_obligatoire_avec_une_chambre(self):
        reponse = self.client.post(reverse("residents:creer"), self.donnees(arrivee=""))
        self.assertFormError(
            reponse.context["formulaire"], "arrivee", "Indiquez la date d'arrivée dans la chambre."
        )

    def test_numero_deja_pris(self):
        reponse = self.client.post(
            reverse("residents:creer"), self.donnees(telephone="06 12 34 56 47")
        )
        self.assertFormError(
            reponse.context["formulaire"],
            None,
            "Ce numéro est déjà utilisé par une autre personne.",
        )

    def test_nom_utilisateur_libre(self):
        self.assertEqual(nom_utilisateur_libre("Awa", "Koné"), "awa.kone-2")
        User.objects.create_user("awa.kone-2")
        self.assertEqual(nom_utilisateur_libre("Awa", "Koné"), "awa.kone-3")
        self.assertEqual(nom_utilisateur_libre("", "!!"), "resident")


class FicheTests(ResidentsTestCase):
    def url(self, resident=None):
        return reverse("residents:fiche", args=[(resident or self.awa).pk])

    def donnees(self, **autres):
        return {
            "first_name": "Awa",
            "last_name": "Koné",
            "telephone": "+33612345647",
            "email": "",
            "chambre": self.c312.pk,
            "arrivee": "2026-09-01",
        } | autres

    def test_affichage(self):
        Sejour.objects.create(resident=self.lucas, chambre=self.c304, arrivee=J1, depart=J2)
        reponse = self.client.get(self.url(self.lucas))
        enregistrer_page("residents-fiche", reponse)
        self.assertContains(reponse, "<h1>Lucas Petit</h1>", html=True)
        self.assertContains(reponse, "Pas encore activé")
        self.assertContains(reponse, "Du <time")
        reponse = self.client.get(self.url())
        # Sur la fiche, le numéro est complet ; la chambre actuelle est choisie.
        self.assertContains(reponse, "06 12 34 56 47")
        formulaire = reponse.context["formulaire"]
        self.assertEqual(formulaire["chambre"].value(), self.c312.pk)
        self.assertEqual(list(formulaire.fields["chambre"].queryset), [self.c304, self.c312])
        self.assertIsNone(formulaire.fields["chambre"].empty_label)

    def test_modification(self):
        reponse = self.client.post(self.url(), self.donnees(last_name="Koné-Diallo"))
        self.assertRedirects(reponse, self.url())
        self.awa.refresh_from_db()
        self.assertEqual(self.awa.last_name, "Koné-Diallo")
        self.assertEqual(self.awa.username, "awa.kone")
        self.assertEqual(self.awa.sejours.count(), 1)

    def test_demenagement_interne(self):
        self.client.post(self.url(), self.donnees(chambre=self.c304.pk, arrivee="2026-11-02"))
        ancien, nouveau = self.awa.sejours.order_by("arrivee")
        self.assertEqual((ancien.chambre, ancien.depart), (self.c312, date(2026, 11, 2)))
        self.assertEqual((nouveau.chambre, nouveau.depart), (self.c304, None))

    def test_correction_de_la_date_d_arrivee(self):
        self.client.post(self.url(), self.donnees(arrivee="2026-08-28"))
        self.assertEqual(sejour_en_cours(self.awa).arrivee, date(2026, 8, 28))

    def test_demenagement_avant_l_arrivee_refuse(self):
        reponse = self.client.post(
            self.url(), self.donnees(chambre=self.c304.pk, arrivee="2026-08-01")
        )
        self.assertFormError(
            reponse.context["formulaire"],
            "arrivee",
            "La date est avant le début du séjour en cours.",
        )
        self.assertEqual(sejour_en_cours(self.awa).chambre, self.c312)
        self.assertContains(reponse, "<h1>Awa Koné</h1>", html=True)

    def test_chambre_obligatoire_pendant_un_sejour(self):
        reponse = self.client.post(self.url(), self.donnees(chambre=""))
        self.assertFormError(reponse.context["formulaire"], "chambre", "Ce champ est obligatoire.")

    def test_les_noms_restent_inchanges_si_la_fiche_est_refusee(self):
        reponse = self.client.post(self.url(), self.donnees(first_name="Zed", telephone="06"))
        self.assertContains(reponse, "<h1>Awa Koné</h1>", html=True)
        self.awa.refresh_from_db()
        self.assertEqual(self.awa.first_name, "Awa")


class ModeleTests(TestCase):
    def test_residents_exclut_l_equipe(self):
        creer_utilisateur("lina")
        creer_utilisateur("yanis", Role.MODERATEUR)
        creer_utilisateur("sam", Role.EDUCATEUR, Role.MODERATEUR)
        creer_utilisateur("nadia", Role.ACCUEIL)
        self.assertQuerySetEqual(
            User.objects.residents().order_by("username"),
            ["lina", "yanis"],
            transform=lambda u: u.username,
        )

    def test_etat_du_compte(self):
        lina = creer_utilisateur("lina")
        self.assertEqual(lina.etat_compte, EtatCompte.EN_ATTENTE)
        lina.last_login = timezone.now() - timedelta(days=1)
        self.assertEqual(lina.etat_compte, EtatCompte.ACTIVE)
        lina.is_active = False
        self.assertEqual(lina.etat_compte, EtatCompte.DESACTIVE)
