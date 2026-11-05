"""Départ d'un résident (carte T09). Données inventées."""

from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from comptes.models import User
from comptes.roles import Role
from comptes.tests.outils import connecter, creer_utilisateur
from journal.models import Action, EntreeJournal
from logement.models import Chambre, Etage, Sejour
from logement.services import sejour_en_cours
from outils.capture_html import enregistrer_page
from residents.depart import (
    cles_de_session,
    depart_enregistre,
    enregistrer_depart,
    fermer_sessions,
)

ARRIVEE = date(2026, 9, 1)


class DepartTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.accueil = creer_utilisateur("nadia", Role.ACCUEIL)
        e3 = Etage.objects.create(numero=3)
        cls.c312 = Chambre.objects.create(numero="312", etage=e3)
        cls.awa = creer_utilisateur(
            "awa.kone", first_name="Awa", last_name="Koné", telephone="+33612345647"
        )
        Sejour.objects.create(resident=cls.awa, chambre=cls.c312, arrivee=ARRIVEE)

    def setUp(self):
        connecter(self.client, self.accueil)

    def url(self):
        return reverse("residents:depart", args=[self.awa.pk])


class ServiceTests(DepartTestCase):
    def test_depart_complet(self):
        # Awa est connectée sur deux appareils.
        telephone, ordinateur = Client(), Client()
        telephone.force_login(self.awa)
        ordinateur.force_login(self.awa)
        self.assertEqual(Client().session.__class__.__name__, "SessionStore")

        recus = []

        def receveur(sender, **kwargs):
            recus.append(kwargs)

        depart_enregistre.connect(receveur)
        self.addCleanup(depart_enregistre.disconnect, receveur)

        le = timezone.localdate()
        sejour = enregistrer_depart(self.awa, le)

        self.awa.refresh_from_db()
        self.assertFalse(self.awa.is_active)
        self.assertFalse(self.awa.has_usable_password())
        self.assertEqual(sejour.depart, le)
        self.assertIsNone(sejour_en_cours(self.awa))
        self.assertIn(self.c312, Chambre.objects.libres())
        self.assertEqual(len(recus), 1)
        self.assertEqual((recus[0]["resident"], recus[0]["sejour"]), (self.awa, sejour))

        entree = EntreeJournal.objects.get(action=Action.DEPART_RESIDENT)
        self.assertEqual(entree.cible, self.awa)
        self.assertEqual(entree.cible_libelle, "Awa Koné (awa.kone)")
        self.assertEqual(entree.details["sessions_fermees"], 2)
        self.assertEqual(
            entree.resume(), f"Chambre 312, départ le {le:%d/%m/%Y}. 2 sessions fermées."
        )
        # Les deux appareils sont déconnectés.
        for client in (telephone, ordinateur):
            self.assertNotIn("_auth_user_id", client.session)

    def test_les_sessions_des_autres_restent(self):
        connecter(Client(), self.accueil)
        Client().force_login(self.awa)
        self.assertEqual(fermer_sessions(cles_de_session(self.awa)), 1)
        self.assertEqual(len(cles_de_session(self.awa)), 0)
        self.assertEqual(len(cles_de_session(self.accueil)), 2)  # celle du setUp et celle-ci

    def test_un_receveur_qui_echoue_annule_tout(self):
        def receveur(sender, **kwargs):
            raise RuntimeError("coupure du wifi impossible")

        depart_enregistre.connect(receveur)
        self.addCleanup(depart_enregistre.disconnect, receveur)
        with self.assertRaises(RuntimeError):
            enregistrer_depart(self.awa, timezone.localdate())
        self.awa.refresh_from_db()
        self.assertTrue(self.awa.is_active)
        self.assertIsNotNone(sejour_en_cours(self.awa))
        self.assertFalse(EntreeJournal.objects.exists())

    def test_sans_sejour(self):
        lina = creer_utilisateur("lina")
        self.assertIsNone(enregistrer_depart(lina, timezone.localdate()))
        lina.refresh_from_db()
        self.assertFalse(lina.is_active)


class PageDepartTests(DepartTestCase):
    def test_confirmation(self):
        reponse = self.client.get(self.url())
        enregistrer_page("residents-depart", reponse)
        self.assertContains(reponse, "Départ de Awa Koné")
        self.assertContains(reponse, "Le séjour en chambre 312 se termine")
        self.assertContains(reponse, 'class="bouton bouton--danger"')
        self.assertContains(reponse, f'max="{timezone.localdate().isoformat()}"')
        self.assertContains(reponse, 'min="2026-09-01"')

    def test_enregistrement(self):
        le = timezone.localdate() - timedelta(days=1)
        reponse = self.client.post(self.url(), {"depart": le.isoformat()}, follow=True)
        self.assertRedirects(reponse, reverse("residents:fiche", args=[self.awa.pk]))
        enregistrer_page("residents-fiche-ancien", reponse)
        self.assertContains(reponse, "Le départ de Awa Koné est enregistré.")
        self.assertContains(reponse, "Cette personne a quitté la résidence le")
        self.assertNotContains(reponse, 'name="chambre"')
        self.assertNotContains(reponse, reverse("residents:depart", args=[self.awa.pk]))
        self.assertEqual(self.awa.sejours.get().depart, le)
        entree = EntreeJournal.objects.get()
        self.assertEqual(entree.acteur, self.accueil)
        self.assertEqual(entree.adresse_ip, "127.0.0.1")

    def test_dates_refusees(self):
        cas = {
            (timezone.localdate() + timedelta(days=1)).isoformat(): "dans le futur",
            "2026-08-31": "avant l&#x27;arrivée dans la chambre (01/09/2026)",
            "": "Ce champ est obligatoire.",
        }
        for valeur, message in cas.items():
            with self.subTest(valeur=valeur):
                reponse = self.client.post(self.url(), {"depart": valeur})
                enregistrer_page("residents-depart-erreur", reponse)
                self.assertContains(reponse, message)
                self.assertContains(reponse, "Le départ n'est pas enregistré.")
        self.awa.refresh_from_db()
        self.assertTrue(self.awa.is_active)

    def test_deja_parti(self):
        enregistrer_depart(self.awa, timezone.localdate())
        reponse = self.client.get(self.url(), follow=True)
        self.assertRedirects(reponse, reverse("residents:fiche", args=[self.awa.pk]))
        self.assertContains(reponse, "Le départ de cette personne est déjà enregistré.")

    def test_reserve_a_la_gestion_des_residents(self):
        connecter(self.client, creer_utilisateur("sam", Role.EDUCATEUR))
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        self.assertEqual(self.client.post(self.url(), {"depart": "2026-11-01"}).status_code, 403)
        reponse = self.client.get(reverse("residents:fiche", args=[self.awa.pk]))
        self.assertNotContains(reponse, "Enregistrer le départ")

    def test_lien_depuis_la_fiche(self):
        reponse = self.client.get(reverse("residents:fiche", args=[self.awa.pk]))
        self.assertContains(reponse, f'href="{self.url()}"')


class ListeApresDepartTests(DepartTestCase):
    def test_anciens_residents_a_part(self):
        enregistrer_depart(self.awa, timezone.localdate())
        creer_utilisateur("lina", first_name="Lina", last_name="Roux")
        reponse = self.client.get(reverse("residents:liste"))
        self.assertEqual([r.username for r in reponse.context["page_obj"]], ["lina"])
        self.assertContains(reponse, "1 résident · ")
        self.assertContains(reponse, '<a href="?compte=desactive">1 ancien résident</a>', html=True)
        reponse = self.client.get(reverse("residents:liste"), {"compte": "desactive"})
        self.assertEqual([r.username for r in reponse.context["page_obj"]], ["awa.kone"])
        self.assertContains(reponse, "Désactivé")

    def test_fiche_d_un_ancien_resident_modifiable_sans_relogement(self):
        enregistrer_depart(self.awa, timezone.localdate())
        reponse = self.client.post(
            reverse("residents:fiche", args=[self.awa.pk]),
            {"first_name": "Awa", "last_name": "Koné", "telephone": "", "email": "a@exemple.fr"},
        )
        self.assertEqual(reponse.status_code, 302)
        self.awa.refresh_from_db()
        self.assertEqual(self.awa.email, "a@exemple.fr")
        self.assertFalse(self.awa.is_active)
        self.assertIsNone(sejour_en_cours(self.awa))
        self.assertEqual(User.objects.get(pk=self.awa.pk).sejours.count(), 1)


class RevueTests(DepartTestCase):
    """Cas trouvés par la relecture indépendante (5 nov.)."""

    def test_une_fiche_ouverte_avant_le_depart_ne_le_defait_pas(self):
        # Le formulaire est préparé (compte actif), puis le départ passe, puis il est envoyé.
        from residents.forms import FormulaireResident

        c313 = Chambre.objects.create(numero="313", etage=self.c312.etage)
        formulaire = FormulaireResident(
            {
                "first_name": "Awa",
                "last_name": "Koné",
                "telephone": "",
                "email": "",
                "chambre": c313.pk,
                "arrivee": timezone.localdate().isoformat(),
            },
            instance=User.objects.get(pk=self.awa.pk),
        )
        self.assertTrue(formulaire.is_valid(), formulaire.errors)
        enregistrer_depart(self.awa, timezone.localdate())
        with self.assertRaisesMessage(ValidationError, "vient d'être enregistré"):
            formulaire.enregistrer()
        self.awa.refresh_from_db()
        self.assertFalse(self.awa.is_active)
        self.assertFalse(Sejour.objects.filter(chambre=c313).exists())

    def test_modifier_l_identite_ne_rouvre_pas_le_compte(self):
        from residents.forms import FormulaireResident

        ancienne = User.objects.get(pk=self.awa.pk)
        enregistrer_depart(self.awa, timezone.localdate())
        # Fiche d'un ancien résident (sans champs de chambre) : seule l'identité est écrite.
        formulaire = FormulaireResident(
            {"first_name": "Awa", "last_name": "Koné", "telephone": "", "email": "a@exemple.fr"},
            instance=User.objects.get(pk=self.awa.pk),
        )
        self.assertTrue(formulaire.is_valid(), formulaire.errors)
        formulaire.enregistrer()
        self.awa.refresh_from_db()
        self.assertFalse(self.awa.is_active)
        self.assertNotEqual(self.awa.password, ancienne.password)

    def test_compte_desactive_ailleurs_mais_encore_loge(self):
        User.objects.filter(pk=self.awa.pk).update(is_active=False)
        # Toujours dans la liste, et son départ peut libérer la chambre.
        reponse = self.client.get(reverse("residents:liste"))
        self.assertEqual([r.username for r in reponse.context["page_obj"]], ["awa.kone"])
        reponse = self.client.get(self.url())
        self.assertEqual(reponse.status_code, 200)
        self.client.post(self.url(), {"depart": timezone.localdate().isoformat()})
        self.assertIn(self.c312, Chambre.objects.libres())

    def test_double_depart(self):
        copie = User.objects.get(pk=self.awa.pk)
        enregistrer_depart(self.awa, timezone.localdate())
        with self.assertRaisesMessage(ValidationError, "déjà enregistré"):
            enregistrer_depart(copie, timezone.localdate())
        self.assertEqual(EntreeJournal.objects.count(), 1)

    def test_comptes_d_administration_jamais_residents(self):
        chef = User.objects.create_superuser("chef", password="x")
        chef.groups.clear()  # même sans groupe
        technicien = User.objects.create_user("tech", is_staff=True)
        residents = set(User.objects.residents().values_list("username", flat=True))
        self.assertNotIn("chef", residents)
        self.assertNotIn("tech", residents)
        self.assertEqual(
            self.client.get(reverse("residents:depart", args=[chef.pk])).status_code, 404
        )
        self.assertEqual(
            self.client.get(reverse("residents:depart", args=[technicien.pk])).status_code, 404
        )

    def test_educateurs_ne_voient_pas_les_anciens_residents(self):
        enregistrer_depart(self.awa, timezone.localdate())
        connecter(self.client, creer_utilisateur("sam", Role.EDUCATEUR))
        reponse = self.client.get(reverse("residents:liste"), {"compte": "desactive"})
        self.assertEqual(list(reponse.context["page_obj"]), [])
        self.assertNotContains(reponse, "ancien résident")
        self.assertNotContains(reponse, 'value="desactive"')
        reponse = self.client.get(reverse("residents:fiche", args=[self.awa.pk]))
        self.assertEqual(reponse.status_code, 404)
