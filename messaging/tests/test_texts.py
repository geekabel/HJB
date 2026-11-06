"""Fields and SMS version of a message (card T20)."""

from datetime import date, time

from django.test import SimpleTestCase

from accounts.models import User
from housing.models import Room
from sms.segments import analyze

from ..models import Campaign
from ..placeholders import check_text, fill, format_time, missing_values, values_for
from ..sms_text import sms_text, to_gsm, words_with


class PlaceholderTests(SimpleTestCase):
    def test_fill(self):
        campaign = Campaign(
            event_date=date(2026, 11, 6), start_time=time(15), end_time=time(17, 30)
        )
        values = values_for(campaign, User(first_name="Awa"), Room(number="312"))
        text = "Bonjour {prénom}, chambre {chambre}, le {date} de {début} à {fin}. {inconnu}"
        self.assertEqual(
            fill(text, values),
            "Bonjour Awa, chambre 312, le vendredi 6 novembre de 15 h à 17 h 30. {inconnu}",
        )

    def test_unknown_fields(self):
        self.assertEqual(check_text("Bonjour {prénom}"), [])
        self.assertEqual(
            check_text("Bonjour {prenom} {heure}"),
            [
                "Champs inconnus : {prenom}, {heure}. "
                "Champs possibles : {prénom}, {chambre}, {date}, {début}, {fin}."
            ],
        )

    def test_missing_values(self):
        campaign = Campaign(body="Le {date} à {début}", sms_body="{fin}")
        self.assertEqual(missing_values(campaign), ["date", "début", "fin"])
        campaign.event_date = date(2026, 11, 6)
        self.assertEqual(missing_values(campaign), ["début", "fin"])

    def test_format_time(self):
        self.assertEqual(format_time(time(8)), "8 h")
        self.assertEqual(format_time(time(8, 5)), "8 h 05")


class SmsTextTests(SimpleTestCase):
    def test_french_characters_replaced(self):
        text = (
            "Si vous êtes absent, c\u2019est «\u00a0noté\u00a0» : déjà là, ça marche\u2026 à côté"
        )
        result = to_gsm(text)
        self.assertEqual(
            result, 'Si vous etes absent, c\'est "noté" : déjà là, ca marche... à coté'
        )
        self.assertEqual(analyze(result).encoding, "GSM-7")
        self.assertEqual(analyze(text).encoding, "UCS-2")

    def test_emoji_kept(self):
        result = sms_text("Fête  ce soir 🎉\n\n  À bientôt ")
        self.assertEqual(result, "Fete ce soir 🎉\nA bientot")
        self.assertEqual(analyze(result).non_gsm, ("🎉",))
        self.assertEqual(words_with(result, "🎉"), ["🎉"])

    def test_review_characters(self):
        # Review of T20: common characters, and no change of meaning.
        self.assertEqual(
            to_gsm("n\u00b0 312 \u2022 rez\u2011de\u2011chauss\u00e9e"), "no 312 - rez-de-chaussée"
        )
        self.assertEqual(to_gsm("\ufb01n \u0151"), "fin o")
        self.assertEqual(to_gsm("\u00bd"), "\u00bd")  # would become "1/2" with another slash
