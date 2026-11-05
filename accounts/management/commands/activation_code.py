"""Issue an activation code from the server (card T14).

Mainly for the first administrator, who has no passkey yet:

    python manage.py activation_code <username> --phone "06 12 34 56 78"

The code is shown only once. Django docs:
https://docs.djangoproject.com/en/6.1/howto/custom-management-commands/
"""

from django.core.management.base import BaseCommand, CommandError

from access.session_policy import is_resident
from accounts.activation_codes import issue_code
from accounts.models import User


class Command(BaseCommand):
    help = "Génère un code d'activation pour un compte et l'affiche une seule fois."

    def add_arguments(self, parser):
        parser.add_argument("username", help="Identifiant du compte (username).")
        parser.add_argument(
            "--phone",
            help="Numéro à enregistrer d'abord (le code SMS de l'étape 2 y sera envoyé).",
        )

    def handle(self, *args, username, **options):
        try:
            person = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f"Aucun compte « {username} ».") from None
        if not person.is_active:
            raise CommandError("Ce compte est désactivé.")
        if options.get("phone"):
            from django.core.exceptions import ValidationError

            person.phone = options["phone"]
            try:
                person.full_clean(validate_unique=True, exclude=["password"])
            except ValidationError as error:
                raise CommandError(" ".join(error.messages)) from None
            person.save(update_fields=["phone"])
        if not person.phone:
            raise CommandError(
                "Ce compte n'a pas de numéro de téléphone : il en faut un pour le code SMS."
            )
        code = issue_code(person, for_staff=not is_resident(person))
        self.stdout.write(f"Code d'activation de {username} : {code}")
        self.stdout.write("Valable 72 heures, une seule fois. À saisir sur la page /activer/.")
