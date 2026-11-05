"""Import CSV et Excel. Toutes les données sont inventées."""

import io
import zipfile
from datetime import date, datetime

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook

from comptes.models import User
from comptes.roles import Role
from comptes.tests.outils import creer_utilisateur
from logement.models import Chambre, Etage, Sejour
from logement.services import sejour_en_cours
from outils.capture_html import enregistrer_page
from residents.importation import (
    LIGNES_MAX,
    TAILLE_DECOMPRESSEE_MAX,
    TAILLE_MAX,
    ErreurFichier,
    LigneImport,
    analyser,
    importer,
    lire_fichier,
)
from residents.models import ImportResidents

AUJOURD_HUI = date(2026, 11, 5)


def csv_(texte, nom="residents.csv", encodage="utf-8-sig"):
    return SimpleUploadedFile(nom, texte.encode(encodage), content_type="text/csv")


def xlsx(lignes, nom="residents.xlsx"):
    classeur = Workbook()
    feuille = classeur.active
    for ligne in lignes:
        feuille.append(ligne)
    tampon = io.BytesIO()
    classeur.save(tampon)
    return SimpleUploadedFile(nom, tampon.getvalue())


class ImportTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.e3 = Etage.objects.create(numero=3)
        cls.c304 = Chambre.objects.create(numero="304", etage=cls.e3)
        cls.c305 = Chambre.objects.create(numero="305", etage=cls.e3)
        cls.c312 = Chambre.objects.create(numero="312", etage=cls.e3)
        cls.ferme = Chambre.objects.create(numero="399", etage=cls.e3, active=False)
        cls.awa = creer_utilisateur(
            "awa.kone", first_name="Awa", last_name="Koné", telephone="+33612345647"
        )
        Sejour.objects.create(resident=cls.awa, chambre=cls.c312, arrivee=date(2026, 9, 1))


class LectureTests(ImportTestCase):
    def test_csv_point_virgule_avec_bom(self):
        lignes = lire_fichier(csv_("Prénom;Nom;Chambre\nInès;Martin;304\n"))
        self.assertEqual(
            lignes, [(1, ["Prénom", "Nom", "Chambre"]), (2, ["Inès", "Martin", "304"])]
        )

    def test_csv_virgule_et_guillemets(self):
        lignes = lire_fichier(csv_('Prénom,Nom\n"Jean, dit Jo",Durand\n'))
        self.assertEqual(lignes[1][1], ["Jean, dit Jo", "Durand"])

    def test_csv_windows_1252(self):
        lignes = lire_fichier(csv_("Prénom;Nom\nLéa;Moreau\n", encodage="cp1252"))
        self.assertEqual(lignes[1][1], ["Léa", "Moreau"])

    def test_lignes_vides_ignorees(self):
        lignes = lire_fichier(csv_("Prénom;Nom\n;\nLéa;Moreau\n\n"))
        # La ligne vide disparaît, mais Léa garde son numéro de ligne : 3.
        self.assertEqual(lignes, [(1, ["Prénom", "Nom"]), (3, ["Léa", "Moreau"])])

    def test_xlsx(self):
        fichier = xlsx(
            [
                ["Prénom", "Nom", "Téléphone", "Arrivée"],
                ["Léa", "Moreau", 612345678, datetime(2026, 9, 1)],
            ]
        )
        lignes = lire_fichier(fichier)
        self.assertEqual(lignes[1], (2, ["Léa", "Moreau", 612345678, datetime(2026, 9, 1)]))

    def test_fichiers_refuses(self):
        cas = {
            "ancien format": (SimpleUploadedFile("a.xls", b"x"), "(.xls)"),
            "extension": (SimpleUploadedFile("a.pdf", b"x"), ".csv ou un .xlsx"),
            "vide": (csv_("\n\n"), "vide"),
            "illisible": (SimpleUploadedFile("a.xlsx", b"pas un classeur"), "illisible"),
            "trop long": (csv_("Prénom;Nom\n" + "A;B\n" * (LIGNES_MAX + 1)), "500 lignes"),
        }
        for nom, (fichier, extrait) in cas.items():
            with self.subTest(nom), self.assertRaisesMessage(ErreurFichier, extrait):
                lire_fichier(fichier)

    def test_trop_lourd(self):
        fichier = csv_("Prénom;Nom\n")
        fichier.size = 3 * 1024 * 1024
        with self.assertRaisesMessage(ErreurFichier, "2 Mo"):
            lire_fichier(fichier)


class AnalyseTests(ImportTestCase):
    def analyser(
        self, *lignes, en_tete=("Prénom", "Nom", "Téléphone", "Chambre", "Arrivée", "E-mail")
    ):
        return analyser(list(enumerate([list(en_tete), *map(list, lignes)], start=1)))

    def erreurs(self, *lignes, **kwargs):
        return [ligne.erreurs for ligne in self.analyser(*lignes, **kwargs)]

    def test_ligne_prete(self):
        (ligne,) = self.analyser(("Inès", "Martin", "07 81 23 45 88", "304", "03/11/2026", ""))
        self.assertTrue(ligne.prete)
        self.assertEqual(ligne.numero, 2)
        self.assertEqual(ligne.telephone, "+33781234588")
        self.assertEqual(ligne.telephone_affiche, "07 81 23 45 88")
        self.assertEqual(ligne.date_arrivee, date(2026, 11, 3))

    def test_en_tetes_souples_et_colonnes_dans_le_desordre(self):
        (ligne,) = self.analyser(
            ("304", "martin", "Inès"), en_tete=(" N° chambre ", "NOM", "prenom")
        )
        self.assertEqual((ligne.prenom, ligne.nom, ligne.chambre), ("Inès", "martin", "304"))
        # Chambre sans date : arrivée le jour de l'import, calculé à ce moment-là.
        self.assertTrue(ligne.arrivee_auto)
        self.assertEqual(ligne.date_arrivee, timezone.localdate())

    def test_en_tetes_obligatoires(self):
        with self.assertRaisesMessage(ErreurFichier, "Il manque « Prenom » et « Nom »"):
            analyser([(1, ["Téléphone"]), (2, ["06 12 34 56 78"])])

    def test_valeurs_venues_d_excel(self):
        (ligne,) = self.analyser(("Léa", "Moreau", 612345678, 304.0, datetime(2026, 9, 1), ""))
        self.assertTrue(ligne.prete, ligne.erreurs)
        self.assertEqual(ligne.telephone, "+33612345678")
        self.assertEqual(ligne.chambre, "304")

    def test_erreurs_expliquees(self):
        cas = [
            (("", "", "", "", "", ""), ["Le prénom manque.", "Le nom manque."]),
            (
                ("A", "B", "06 12 34", "", "", ""),
                ["Numéro « 06 12 34 » : Ce numéro n'existe pas. Vérifiez les chiffres."],
            ),
            (("A", "B", "06 12 34 56 47", "", "", ""), ["Ce numéro est déjà celui de Awa Koné."]),
            (("A", "B", "", "999", "", ""), ["La chambre 999 n'existe pas."]),
            (("A", "B", "", "399", "", ""), ["La chambre 399 est fermée."]),
            (("A", "B", "", "312", "", ""), ["La chambre 312 est déjà occupée par Awa Koné."]),
            (
                ("A", "B", "", "304", "31/02/2026", ""),
                ["« 31/02/2026 » n'est pas une date. Écrivez-la comme 01/09/2026."],
            ),
            (("A", "B", "", "", "", "a@"), ["« a@ » n'est pas une adresse e-mail."]),
        ]
        for ligne, attendu in cas:
            with self.subTest(ligne=ligne):
                self.assertEqual(self.erreurs(ligne), [attendu])

    def test_doublons_dans_le_fichier(self):
        erreurs = self.erreurs(
            ("A", "B", "07 81 23 45 88", "304", "", ""),
            ("C", "D", "+33 7 81 23 45 88", "304", "", ""),
        )
        self.assertEqual(erreurs[0], [])
        self.assertEqual(
            erreurs[1], ["Même numéro que la ligne 2.", "Même chambre que la ligne 2."]
        )

    def test_meme_nom_signale_sans_bloquer(self):
        (ligne,) = self.analyser(("awa", "KONÉ", "", "", "", ""))
        self.assertTrue(ligne.prete)
        self.assertIn("Une fiche existe déjà à ce nom", ligne.avertissements[0])

    def test_nombre_de_requetes_independant_du_nombre_de_lignes(self):
        lignes = [(f"P{i}", f"N{i}", f"07 81 23 45 {i:02}", "304", "", "") for i in range(40)]
        with self.assertNumQueries(4):
            self.analyser(*lignes)


class ImporterTests(ImportTestCase):
    def test_tout_ou_rien(self):
        bonne = LigneImport(
            numero=2, prenom="Inès", nom="Martin", chambre="304", arrivee="2026-11-03"
        )
        # Ligne qui paraît prête mais vise une chambre occupée : refusée au dernier moment.
        piege = LigneImport(
            numero=3, prenom="Léa", nom="Moreau", chambre="312", arrivee="2026-11-03"
        )
        avant = User.objects.count()
        with self.assertRaises(ValidationError):
            importer([bonne, piege])
        self.assertEqual(User.objects.count(), avant)
        self.assertFalse(Sejour.objects.filter(chambre=self.c304).exists())


class PagesImportTests(ImportTestCase):
    def setUp(self):
        self.client.force_login(creer_utilisateur("nadia", Role.ACCUEIL))

    def envoyer(self, fichier):
        return self.client.post(reverse("residents:import"), {"fichier": fichier})

    def confirmer(self, pretes, jeton=None, action="importer", **kwargs):
        jeton = jeton or self.client.session["import_residents"]["jeton"]
        return self.client.post(
            reverse("residents:import_apercu"),
            {"action": action, "pretes": pretes, "jeton": jeton},
            **kwargs,
        )

    def fichier_type(self):
        return csv_(
            "Prénom;Nom;Téléphone;Chambre;Arrivée\n"
            "Inès;Martin;07 81 23 45 88;304;03/11/2026\n"
            "Léa;Moreau;06 12 34;;\n"
            "Moussa;Diallo;;305;01/11/2026\n"
            "Zoé;Bernard;06 12 34 56 47;;\n"
        )

    def test_reserve_a_la_gestion_des_residents(self):
        self.client.force_login(creer_utilisateur("sam", Role.EDUCATEUR))
        for nom in ["import", "import_apercu", "import_modele"]:
            self.assertEqual(self.client.get(reverse(f"residents:{nom}")).status_code, 403)

    def test_page_d_envoi(self):
        reponse = self.client.get(reverse("residents:import"))
        enregistrer_page("residents-import", reponse)
        self.assertContains(reponse, 'enctype="multipart/form-data"')
        self.assertContains(reponse, 'accept=".csv,.xlsx"')
        reponse = self.client.get(reverse("residents:liste"))
        self.assertContains(reponse, "Importer CSV ou Excel")

    def test_fichier_refuse(self):
        reponse = self.envoyer(SimpleUploadedFile("vieux.xls", b"x"))
        enregistrer_page("residents-import-erreur", reponse)
        self.assertContains(reponse, "L&#x27;ancien format Excel (.xls)")
        self.assertContains(reponse, 'aria-invalid="true"')

    def test_apercu_puis_import(self):
        reponse = self.envoyer(self.fichier_type())
        self.assertRedirects(reponse, reverse("residents:import_apercu"))
        reponse = self.client.get(reverse("residents:import_apercu"))
        enregistrer_page("residents-import-apercu", reponse)
        self.assertContains(reponse, "Aperçu · residents.csv")
        self.assertContains(reponse, "2 prêtes")
        self.assertContains(reponse, "2 à corriger")
        self.assertContains(reponse, "Ce numéro est déjà celui de Awa Koné.")
        self.assertContains(reponse, 'name="pretes" value="2,4"')
        self.assertContains(reponse, "Importer les 2 lignes prêtes")

        reponse = self.confirmer("2,4", follow=True)
        self.assertRedirects(reponse, reverse("residents:liste"))
        self.assertContains(reponse, "2 résidents importés.")
        ines = User.objects.get(first_name="Inès")
        self.assertEqual(ines.telephone, "+33781234588")
        self.assertFalse(ines.has_usable_password())
        self.assertEqual(sejour_en_cours(ines).arrivee, date(2026, 11, 3))
        moussa = User.objects.get(first_name="Moussa")
        self.assertEqual(sejour_en_cours(moussa).chambre, self.c305)
        self.assertFalse(User.objects.filter(first_name__in=["Léa", "Zoé"]).exists())
        self.assertNotIn("import_residents", self.client.session)

    def test_situation_changee_avant_la_confirmation(self):
        self.envoyer(self.fichier_type())
        # Entre l'aperçu et la confirmation, quelqu'un loge une autre personne en 304.
        Sejour.objects.create(
            resident=creer_utilisateur("x"), chambre=self.c304, arrivee=AUJOURD_HUI
        )
        reponse = self.confirmer("2,4")
        self.assertContains(reponse, "La situation a changé depuis l'aperçu.")
        self.assertContains(reponse, 'name="pretes" value="4"')
        self.assertFalse(User.objects.filter(first_name="Inès").exists())

    def test_annuler(self):
        self.envoyer(self.fichier_type())
        reponse = self.confirmer("", action="annuler", follow=True)
        self.assertRedirects(reponse, reverse("residents:import"))
        self.assertContains(reponse, "Import annulé. Aucune fiche n&#x27;a été créée.")
        self.assertFalse(User.objects.filter(first_name="Inès").exists())

    def test_apercu_sans_fichier(self):
        reponse = self.client.get(reverse("residents:import_apercu"))
        self.assertRedirects(reponse, reverse("residents:import"))

    def test_xlsx_de_bout_en_bout(self):
        self.envoyer(
            xlsx([["Nom", "Prénom", "Portable", "Chambre"], ["Diallo", "Moussa", 781234588, 305]])
        )
        self.confirmer("2")
        moussa = User.objects.get(first_name="Moussa")
        self.assertEqual(moussa.telephone, "+33781234588")
        self.assertEqual(sejour_en_cours(moussa).chambre, self.c305)

    def test_modele_csv(self):
        reponse = self.client.get(reverse("residents:import_modele"))
        self.assertEqual(reponse["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("attachment", reponse["Content-Disposition"])
        texte = reponse.content.decode("utf-8-sig")
        self.assertEqual(texte, "Prénom;Nom;Téléphone;Chambre;Arrivée;E-mail\r\n")
        # Le modèle se relit sans erreur.
        lignes = lire_fichier(SimpleUploadedFile("modele.csv", reponse.content))
        self.assertEqual(len(lignes), 1)


class FichiersPiegesTests(ImportTestCase):
    """Fichiers abîmés ou piégés : refusés avec un message, jamais une erreur 500."""

    def test_lignes_vides_ne_font_pas_perdre_de_lignes(self):
        lignes = "".join(f"P{i};N{i}\n" for i in range(LIGNES_MAX))
        fichier = csv_("Prénom;Nom\n\n\n" + lignes + "\n\n")
        self.assertEqual(len(lire_fichier(fichier)), LIGNES_MAX + 1)
        with self.assertRaisesMessage(ErreurFichier, "500 lignes"):
            lire_fichier(csv_("Prénom;Nom\n\n" + lignes + "Un;De trop\n"))

    def test_trop_de_lignes_vides(self):
        with self.assertRaisesMessage(ErreurFichier, "500 lignes"):
            lire_fichier(csv_("Prénom;Nom\n" + ";\n" * 6000))

    def test_csv_illisible(self):
        cas = {
            "encodage": (SimpleUploadedFile("a.csv", b"Pr\x81nom;Nom\n"), "illisibles"),
            "cellule géante": (csv_('Prénom;Nom\n"' + "x" * 200_000 + '";B\n'), "mal formé"),
        }
        for nom, (fichier, extrait) in cas.items():
            with self.subTest(nom), self.assertRaisesMessage(ErreurFichier, extrait):
                lire_fichier(fichier)

    def _xlsx_modifie(self, modifier):
        source = xlsx([["Prénom", "Nom"], ["Léa", "Moreau"]])
        entree, sortie = io.BytesIO(source.read()), io.BytesIO()
        with (
            zipfile.ZipFile(entree) as zin,
            zipfile.ZipFile(sortie, "w", zipfile.ZIP_DEFLATED) as zout,
        ):
            for info in zin.infolist():
                zout.writestr(info, modifier(info.filename, zin.read(info.filename)))
            if modifier("ajout", None) is not None:
                zout.writestr("ajout.bin", modifier("ajout", None))
        return SimpleUploadedFile("a.xlsx", sortie.getvalue())

    def test_xlsx_xml_abime(self):
        fichier = self._xlsx_modifie(
            lambda nom, contenu: contenu[:-40] if nom.endswith("sheet1.xml") else contenu
        )
        with self.assertRaisesMessage(ErreurFichier, "illisible"):
            lire_fichier(fichier)

    def test_xlsx_qui_gonfle(self):
        gros = b"0" * (TAILLE_DECOMPRESSEE_MAX + 1)
        fichier = self._xlsx_modifie(lambda nom, contenu: gros if nom == "ajout" else contenu)
        self.assertLess(fichier.size, TAILLE_MAX)
        with self.assertRaisesMessage(ErreurFichier, "illisible"):
            lire_fichier(fichier)


class SejourTermineTests(ImportTestCase):
    def test_arrivee_pendant_un_ancien_sejour(self):
        Sejour.objects.create(
            resident=creer_utilisateur("ancien"),
            chambre=self.c305,
            arrivee=date(2025, 9, 1),
            depart=date(2026, 6, 30),
        )
        lignes = analyser(
            [(1, ["Prénom", "Nom", "Chambre", "Arrivée"]), (2, ["A", "B", "305", "01/03/2026"])]
        )
        self.assertEqual(
            lignes[0].erreurs,
            [
                "La chambre 305 était occupée jusqu'au 30/06/2026 : "
                "l'arrivée doit être à partir de cette date."
            ],
        )

    def test_l_erreur_d_import_donne_la_ligne(self):
        piege = LigneImport(
            numero=7, prenom="Léa", nom="Moreau", chambre="312", arrivee="2026-11-03"
        )
        with self.assertRaisesMessage(ValidationError, "Ligne 7 :"):
            importer([piege])


class ConfirmationTests(PagesImportTests):
    def fichier(self, nom, prenom):
        return csv_(f"Prénom;Nom\n{prenom};Test\n", nom=nom)

    def test_deux_onglets(self):
        self.envoyer(self.fichier("a.csv", "Alice"))
        jeton_a = self.client.session["import_residents"]["jeton"]
        self.envoyer(self.fichier("b.csv", "Bruno"))
        reponse = self.confirmer("2", jeton=jeton_a)
        self.assertContains(reponse, "Un autre fichier a été envoyé depuis.")
        self.assertContains(reponse, "Aperçu · b.csv")
        self.assertFalse(User.objects.filter(last_name="Test").exists())

    def test_double_envoi(self):
        self.envoyer(self.fichier("a.csv", "Alice"))
        donnees = self.client.session["import_residents"]
        self.confirmer("2")
        # Seconde requête partie avant que la première ait vidé la session.
        session = self.client.session
        session["import_residents"] = donnees
        session.save()
        reponse = self.confirmer("2", follow=True)
        self.assertContains(reponse, "Cet import a déjà été fait.")
        self.assertEqual(User.objects.filter(first_name="Alice").count(), 1)
        trace = ImportResidents.objects.get()
        self.assertEqual((trace.fichier, trace.nombre), ("a.csv", 1))

    def test_apercu_expire(self):
        self.envoyer(self.fichier("a.csv", "Alice"))
        session = self.client.session
        session["import_residents"]["cree_le"] -= 2 * 60 * 60
        session.save()
        reponse = self.client.get(reverse("residents:import_apercu"), follow=True)
        self.assertRedirects(reponse, reverse("residents:import"))
        self.assertContains(reponse, "L&#x27;aperçu a expiré.")
        self.assertNotIn("import_residents", self.client.session)

    def test_arrivee_du_jour_de_l_import(self):
        self.envoyer(csv_("Prénom;Nom;Chambre\nAlice;Test;304\n"))
        reponse = self.client.get(reverse("residents:import_apercu"))
        self.assertContains(reponse, "Aujourd'hui")
        self.confirmer("2")
        alice = User.objects.get(first_name="Alice")
        self.assertEqual(sejour_en_cours(alice).arrivee, timezone.localdate())
