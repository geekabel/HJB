from datetime import date

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from comptes.roles import Role
from comptes.tests.outils import connecter, creer_utilisateur

from .models import Chambre, Etage, Sejour
from .services import affecter_chambre, sejour_en_cours

J1 = date(2026, 9, 1)
J2 = date(2026, 10, 1)
J3 = date(2026, 11, 1)


def codes(erreur, champ):
    return [e.code for e in erreur.error_dict.get(champ, [])]


class LogementTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.rdc = Etage.objects.create(numero=0)
        cls.e3 = Etage.objects.create(numero=3)
        cls.c312 = Chambre.objects.create(numero="312", etage=cls.e3)
        cls.c304 = Chambre.objects.create(numero="304", etage=cls.e3)
        cls.awa = creer_utilisateur("awa", first_name="Awa", last_name="Koné")
        cls.ines = creer_utilisateur("ines", first_name="Inès", last_name="Martin")


class LibellesTests(LogementTestCase):
    def test_etages(self):
        self.assertEqual(str(self.rdc), "Rez-de-chaussée")
        self.assertEqual(str(Etage(numero=1)), "1er étage")
        self.assertEqual(str(self.e3), "3e étage")
        self.assertEqual(self.e3.libelle_court, "3e")
        self.assertEqual(str(Etage(numero=2, nom="Aile nord")), "Aile nord")

    def test_numero_de_chambre_nettoye(self):
        chambre = Chambre(numero=" 12b ", etage=self.rdc)
        chambre.full_clean()
        self.assertEqual(chambre.numero, "12B")


class ContraintesTests(LogementTestCase):
    """Les règles tiennent même sans passer par la validation (base de données)."""

    def test_une_chambre_un_seul_sejour_en_cours(self):
        Sejour.objects.create(resident=self.awa, chambre=self.c312, arrivee=J1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Sejour.objects.create(resident=self.ines, chambre=self.c312, arrivee=J2)

    def test_un_resident_un_seul_sejour_en_cours(self):
        Sejour.objects.create(resident=self.awa, chambre=self.c312, arrivee=J1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Sejour.objects.create(resident=self.awa, chambre=self.c304, arrivee=J2)

    def test_depart_avant_arrivee_refuse(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Sejour.objects.create(resident=self.awa, chambre=self.c312, arrivee=J2, depart=J1)

    def test_historique_autorise(self):
        Sejour.objects.create(resident=self.awa, chambre=self.c312, arrivee=J1, depart=J2)
        Sejour.objects.create(resident=self.ines, chambre=self.c312, arrivee=J2)
        Sejour.objects.create(resident=self.awa, chambre=self.c304, arrivee=J2)
        self.assertEqual(Sejour.objects.en_cours().count(), 2)


class ValidationTests(LogementTestCase):
    """full_clean() donne des messages clairs avant d'atteindre la base."""

    def test_messages_des_contraintes(self):
        Sejour.objects.create(resident=self.awa, chambre=self.c312, arrivee=J1)
        with self.assertRaises(ValidationError) as ctx:
            Sejour(resident=self.ines, chambre=self.c312, arrivee=J2).full_clean()
        self.assertIn("chambre_occupee", [e.code for e in ctx.exception.error_dict["__all__"]])
        with self.assertRaises(ValidationError) as ctx:
            Sejour(resident=self.awa, chambre=self.c304, arrivee=J2).full_clean()
        self.assertIn("resident_deja_loge", [e.code for e in ctx.exception.error_dict["__all__"]])

    def test_chambre_fermee(self):
        self.c304.active = False
        self.c304.save()
        with self.assertRaises(ValidationError) as ctx:
            Sejour(resident=self.awa, chambre=self.c304, arrivee=J1).full_clean()
        self.assertEqual(codes(ctx.exception, "chambre"), ["chambre_fermee"])
        # Un séjour passé dans une chambre fermée depuis reste saisissable.
        Sejour(resident=self.awa, chambre=self.c304, arrivee=J1, depart=J2).full_clean()

    def test_chevauchement_dans_la_meme_chambre(self):
        Sejour.objects.create(resident=self.awa, chambre=self.c312, arrivee=J1, depart=J3)
        with self.assertRaises(ValidationError) as ctx:
            Sejour(resident=self.ines, chambre=self.c312, arrivee=J2).full_clean()
        self.assertEqual(codes(ctx.exception, "chambre"), ["chambre_chevauchement"])
        with self.assertRaises(ValidationError):
            Sejour(resident=self.ines, chambre=self.c312, arrivee=J1, depart=J2).full_clean()

    def test_meme_jour_de_releve_autorise(self):
        Sejour.objects.create(resident=self.awa, chambre=self.c312, arrivee=J1, depart=J2)
        Sejour(resident=self.ines, chambre=self.c312, arrivee=J2).full_clean()

    def test_chevauchement_pour_la_meme_personne(self):
        Sejour.objects.create(resident=self.awa, chambre=self.c312, arrivee=J1, depart=J3)
        with self.assertRaises(ValidationError) as ctx:
            Sejour(resident=self.awa, chambre=self.c304, arrivee=J2, depart=J3).full_clean()
        self.assertEqual(codes(ctx.exception, "resident"), ["resident_chevauchement"])

    def test_sejour_passe_croise_un_sejour_en_cours(self):
        Sejour.objects.create(resident=self.awa, chambre=self.c312, arrivee=J2)
        with self.assertRaises(ValidationError) as ctx:
            Sejour(resident=self.ines, chambre=self.c312, arrivee=J1, depart=J3).full_clean()
        self.assertEqual(codes(ctx.exception, "chambre"), ["chambre_chevauchement"])


class ChambresLibresTests(LogementTestCase):
    def test_libres(self):
        # 312 occupée, 304 libre, 305 fermée, 306 libre après un départ.
        Sejour.objects.create(resident=self.awa, chambre=self.c312, arrivee=J1)
        Chambre.objects.create(numero="305", etage=self.e3, active=False)
        c306 = Chambre.objects.create(numero="306", etage=self.e3)
        Sejour.objects.create(resident=self.ines, chambre=c306, arrivee=J1, depart=J2)
        self.assertQuerySetEqual(
            Chambre.objects.libres(), ["304", "306"], transform=lambda c: c.numero
        )


class AffecterChambreTests(LogementTestCase):
    def test_premiere_arrivee(self):
        sejour = affecter_chambre(self.awa, self.c312, J1)
        self.assertEqual((sejour.chambre, sejour.arrivee, sejour.depart), (self.c312, J1, None))

    def test_demenagement_interne(self):
        affecter_chambre(self.awa, self.c312, J1)
        nouveau = affecter_chambre(self.awa, self.c304, J2)
        self.assertEqual(nouveau.chambre, self.c304)
        ancien = self.awa.sejours.get(chambre=self.c312)
        self.assertEqual(ancien.depart, J2)
        self.assertEqual(sejour_en_cours(self.awa), nouveau)

    def test_correction_le_jour_meme(self):
        premier = affecter_chambre(self.awa, self.c312, J1)
        corrige = affecter_chambre(self.awa, self.c304, J1)
        self.assertEqual(corrige.pk, premier.pk)
        self.assertEqual(self.awa.sejours.count(), 1)

    def test_meme_chambre_sans_effet(self):
        premier = affecter_chambre(self.awa, self.c312, J1)
        self.assertEqual(affecter_chambre(self.awa, self.c312, J2).pk, premier.pk)

    def test_chambre_occupee_refusee_sans_rien_changer(self):
        affecter_chambre(self.awa, self.c312, J1)
        affecter_chambre(self.ines, self.c304, J1)
        with self.assertRaises(ValidationError):
            affecter_chambre(self.ines, self.c312, J2)
        # La transaction annule la fin du séjour de 304.
        self.assertEqual(sejour_en_cours(self.ines).chambre, self.c304)

    def test_date_avant_le_sejour_en_cours(self):
        affecter_chambre(self.awa, self.c312, J2)
        with self.assertRaises(ValidationError):
            affecter_chambre(self.awa, self.c304, J1)


class AdministrationTests(LogementTestCase):
    def setUp(self):
        admin = creer_utilisateur("chef", Role.ADMIN, is_staff=True, is_superuser=True)
        connecter(self.client, admin)

    def test_pages_de_l_administration(self):
        Sejour.objects.create(resident=self.awa, chambre=self.c312, arrivee=J1)
        for nom in ["etage", "chambre", "sejour"]:
            with self.subTest(nom=nom):
                reponse = self.client.get(reverse(f"admin:logement_{nom}_changelist"))
                self.assertEqual(reponse.status_code, 200)
        reponse = self.client.get(
            reverse("admin:logement_chambre_changelist"), {"occupation": "libre"}
        )
        self.assertContains(reponse, "304")
        self.assertNotContains(reponse, ">312<")
        # Une chambre fermée et vide n'est ni libre ni occupée.
        Chambre.objects.create(numero="399", etage=self.e3, active=False)
        reponse = self.client.get(
            reverse("admin:logement_chambre_changelist"), {"occupation": "occupee"}
        )
        self.assertEqual([c.numero for c in reponse.context["cl"].result_list], ["312"])
        reponse = self.client.get(reverse("admin:logement_etage_change", args=[self.e3.pk]))
        self.assertEqual(reponse.status_code, 200)

    def test_saisie_d_un_etage_et_de_ses_chambres(self):
        reponse = self.client.post(
            reverse("admin:logement_etage_add"),
            {
                "numero": "1",
                "nom": "",
                "ordre_visite": "1",
                "chambres-TOTAL_FORMS": "2",
                "chambres-INITIAL_FORMS": "0",
                "chambres-0-numero": "101",
                "chambres-0-active": "on",
                "chambres-1-numero": "102",
                "chambres-1-active": "on",
            },
        )
        self.assertEqual(reponse.status_code, 302)
        self.assertEqual(
            list(Etage.objects.get(numero=1).chambres.values_list("numero", flat=True)),
            ["101", "102"],
        )
