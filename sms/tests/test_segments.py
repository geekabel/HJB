from django.test import SimpleTestCase

from sms.segments import analyze


class SegmentsTests(SimpleTestCase):
    def check(self, text, encoding, units, segments):
        info = analyze(text)
        self.assertEqual((info.encoding, info.units, info.segments), (encoding, units, segments))
        return info

    def test_empty_message(self):
        self.check("", "GSM-7", 0, 0)

    def test_gsm7_limits(self):
        self.check("a" * 160, "GSM-7", 160, 1)
        self.check("a" * 161, "GSM-7", 161, 2)
        self.check("a" * 306, "GSM-7", 306, 2)  # 2 x 153
        self.check("a" * 307, "GSM-7", 307, 3)

    def test_ucs2_limits(self):
        self.check("ê" * 70, "UCS-2", 70, 1)
        self.check("ê" * 71, "UCS-2", 71, 2)
        self.check("ê" * 134, "UCS-2", 134, 2)  # 2 x 67
        self.check("ê" * 135, "UCS-2", 135, 3)

    def test_french_accents(self):
        # é è à ù are in the GSM alphabet; ê, ç and the typographic apostrophe are not.
        self.check("Réunion à l'accueil, où ? Là-bas.", "GSM-7", 33, 1)
        info = self.check("Fête de la résidence", "UCS-2", 20, 1)
        self.assertEqual(info.non_gsm, ("ê",))
        info = self.check("Rendez-vous à l\u2019accueil, reçu", "UCS-2", 29, 1)
        self.assertEqual(info.non_gsm, ("\u2019", "ç"))

    def test_gsm_extension_counts_double(self):
        self.check("Loyer : 300 €", "GSM-7", 14, 1)
        self.check("€" * 80, "GSM-7", 160, 1)
        # 77 "€" = 154 septets: too much for a 153 long-message segment, without splitting a €.
        info = self.check("€" * 81, "GSM-7", 162, 2)
        self.assertEqual(info.remaining, 153 - 10)  # 76 € (152) in the 1st, 5 € (10) in the 2nd

    def test_emoji_counts_double(self):
        self.check("Bravo 🎉", "UCS-2", 8, 1)
        self.check("🎉" * 35, "UCS-2", 70, 1)
        info = self.check("🎉" * 36, "UCS-2", 72, 2)
        self.assertEqual(info.remaining, 67 - 6)  # 33 emoji (66) then 3 emoji (6)

    def test_remaining(self):
        self.assertEqual(analyze("Bonjour").remaining, 153)
        self.assertEqual(analyze("a" * 200).remaining, 106)
