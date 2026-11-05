"""Send a test SMS with the active provider.

    python manage.py send_test_sms "06 12 34 56 78" "Bonjour, ceci est un essai."

Django docs: https://docs.djangoproject.com/en/6.1/howto/custom-management-commands/
"""

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from accounts.phone import normalize_phone
from sms.providers.base import SmsError
from sms.segments import analyze
from sms.service import active_provider, send_sms


class Command(BaseCommand):
    help = "Envoie un SMS d'essai avec le fournisseur configuré (DJANGO_SMS_PROVIDER)."

    def add_arguments(self, parser):
        parser.add_argument("number", help="Numéro de portable, par exemple « 06 12 34 56 78 ».")
        parser.add_argument("text", help="Texte du SMS.")

    def handle(self, number, text, **options):
        try:
            number = normalize_phone(number)
        except ValidationError as error:
            raise CommandError(error.messages[0]) from error
        info = analyze(text)
        self.stdout.write(
            f"Fournisseur : {active_provider().name}. Codage : {info.encoding}, "
            f"{info.units} caractères, {info.segments} SMS."
        )
        if info.non_gsm:
            self.stdout.write(f"Caractères qui imposent l'UCS-2 : {' '.join(info.non_gsm)}")
        try:
            result = send_sms(number, text)
        except SmsError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(self.style.SUCCESS(f"Envoyé. Identifiant : {result.message_id}"))
