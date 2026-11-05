"""Envoie un SMS d'essai avec le fournisseur actif.

    python manage.py envoyer_sms_essai "06 12 34 56 78" "Bonjour, ceci est un essai."

Doc : https://docs.djangoproject.com/en/6.1/howto/custom-management-commands/
"""

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from comptes.telephone import normaliser_telephone
from sms.fournisseurs.base import ErreurSms
from sms.segments import analyser
from sms.service import envoyer_sms, fournisseur_actif


class Command(BaseCommand):
    help = "Envoie un SMS d'essai avec le fournisseur configuré (DJANGO_SMS_FOURNISSEUR)."

    def add_arguments(self, parser):
        parser.add_argument("numero", help="Numéro de portable, par exemple « 06 12 34 56 78 ».")
        parser.add_argument("texte", help="Texte du SMS.")

    def handle(self, numero, texte, **options):
        try:
            numero = normaliser_telephone(numero)
        except ValidationError as erreur:
            raise CommandError(erreur.messages[0]) from erreur
        info = analyser(texte)
        self.stdout.write(
            f"Fournisseur : {fournisseur_actif().nom}. Codage : {info.encodage}, "
            f"{info.unites} caractères, {info.segments} SMS."
        )
        if info.hors_gsm:
            self.stdout.write(f"Caractères qui imposent l'UCS-2 : {' '.join(info.hors_gsm)}")
        try:
            resultat = envoyer_sms(numero, texte)
        except ErreurSms as erreur:
            raise CommandError(str(erreur)) from erreur
        self.stdout.write(self.style.SUCCESS(f"Envoyé. Identifiant : {resultat.identifiant}"))
