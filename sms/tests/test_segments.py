from django.test import SimpleTestCase

from sms.segments import analyser


class SegmentsTests(SimpleTestCase):
    def verifier(self, texte, encodage, unites, segments):
        info = analyser(texte)
        self.assertEqual((info.encodage, info.unites, info.segments), (encodage, unites, segments))
        return info

    def test_message_vide(self):
        self.verifier("", "GSM-7", 0, 0)

    def test_limites_gsm7(self):
        self.verifier("a" * 160, "GSM-7", 160, 1)
        self.verifier("a" * 161, "GSM-7", 161, 2)
        self.verifier("a" * 306, "GSM-7", 306, 2)  # 2 x 153
        self.verifier("a" * 307, "GSM-7", 307, 3)

    def test_limites_ucs2(self):
        self.verifier("ê" * 70, "UCS-2", 70, 1)
        self.verifier("ê" * 71, "UCS-2", 71, 2)
        self.verifier("ê" * 134, "UCS-2", 134, 2)  # 2 x 67
        self.verifier("ê" * 135, "UCS-2", 135, 3)

    def test_accents_francais(self):
        # é è à ù sont dans l'alphabet GSM ; ê, ç et l'apostrophe typographique non.
        self.verifier("Réunion à l'accueil, où ? Là-bas.", "GSM-7", 33, 1)
        info = self.verifier("Fête de la résidence", "UCS-2", 20, 1)
        self.assertEqual(info.hors_gsm, ("ê",))
        info = self.verifier("Rendez-vous à l\u2019accueil, reçu", "UCS-2", 29, 1)
        self.assertEqual(info.hors_gsm, ("\u2019", "ç"))

    def test_extension_gsm_compte_double(self):
        self.verifier("Loyer : 300 €", "GSM-7", 14, 1)
        self.verifier("€" * 80, "GSM-7", 160, 1)
        # 77 « € » = 154 septets : trop pour un SMS de 153 en message long, sans couper un €.
        info = self.verifier("€" * 81, "GSM-7", 162, 2)
        self.assertEqual(info.restant, 153 - 10)  # 76 € (152) dans le 1er, 5 € (10) dans le 2e

    def test_emoji_compte_double(self):
        self.verifier("Bravo 🎉", "UCS-2", 8, 1)
        self.verifier("🎉" * 35, "UCS-2", 70, 1)
        info = self.verifier("🎉" * 36, "UCS-2", 72, 2)
        self.assertEqual(info.restant, 67 - 6)  # 33 emoji (66) puis 3 emoji (6)

    def test_restant(self):
        self.assertEqual(analyser("Bonjour").restant, 153)
        self.assertEqual(analyser("a" * 200).restant, 106)
