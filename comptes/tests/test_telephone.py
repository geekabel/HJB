from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import SimpleTestCase, TestCase

from comptes.models import User
from comptes.telephone import afficher_telephone, masquer_telephone, normaliser_telephone

# Numéros d'exemple inventés, dans des plages valides.


class NormaliserTelephoneTests(SimpleTestCase):
    def test_formats_courants_vers_e164(self):
        for saisie in ("06 12 34 56 78", "06.12.34.56.78", "+33 6 12 34 56 78", "0033612345678"):
            with self.subTest(saisie=saisie):
                self.assertEqual(normaliser_telephone(saisie), "+33612345678")

    def test_numero_etranger(self):
        self.assertEqual(normaliser_telephone("+32 470 12 34 56"), "+32470123456")

    def test_vide(self):
        self.assertEqual(normaliser_telephone("  "), "")

    def test_refus_avec_code_explicite(self):
        cas = {
            "06 12": "telephone_invalide",
            "bonjour": "telephone_illisible",
            "03 84 00 00 00": "telephone_non_portable",
        }
        for saisie, code in cas.items():
            with self.subTest(saisie=saisie), self.assertRaises(ValidationError) as ctx:
                normaliser_telephone(saisie)
            self.assertEqual(ctx.exception.code, code)


class TelephoneUtilisateurTests(TestCase):
    def test_full_clean_normalise_avant_les_validateurs(self):
        utilisateur = User(username="awa", telephone="06 12 34 56 78")
        utilisateur.set_unusable_password()
        utilisateur.full_clean()
        self.assertEqual(utilisateur.telephone, "+33612345678")

    def test_full_clean_explique_l_erreur(self):
        utilisateur = User(username="awa", telephone="06 12")
        utilisateur.set_unusable_password()
        with self.assertRaises(ValidationError) as ctx:
            utilisateur.full_clean()
        self.assertIn("telephone", ctx.exception.error_dict)

    def test_un_numero_par_personne(self):
        User.objects.create_user(username="a", telephone="+33612345678")
        with self.assertRaises(IntegrityError):
            User.objects.create_user(username="b", telephone="+33612345678")

    def test_plusieurs_comptes_sans_numero(self):
        User.objects.create_user(username="a")
        User.objects.create_user(username="b")
        self.assertEqual(User.objects.filter(telephone="").count(), 2)


class AffichageTests(SimpleTestCase):
    def test_afficher_et_masquer(self):
        cas = {
            "+33612345647": ("06 12 34 56 47", "06 •• •• •• 47"),
            "+41791234567": ("+41 79 123 45 67", "+41 •• ••• •• 67"),
            "": ("", ""),
        }
        # Numéro illisible pour phonenumbers : masqué quand même, sans erreur.
        self.assertEqual(masquer_telephone("+999999999"), "+99•••••99")
        for e164, (affiche, masque) in cas.items():
            with self.subTest(e164=e164):
                self.assertEqual(afficher_telephone(e164), affiche)
                self.assertEqual(masquer_telephone(e164), masque)
