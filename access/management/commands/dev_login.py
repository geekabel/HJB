"""Print a login link without a passkey, in development only (see access/dev_login.py).

python manage.py dev_login <username>
"""

from django.core.management.base import BaseCommand, CommandError

from access import dev_login
from accounts.models import User


class Command(BaseCommand):
    help = (
        "En développement seulement : affiche un lien de connexion sans clé d'accès, "
        "valable 10 minutes et une seule fois."
    )

    def add_arguments(self, parser):
        parser.add_argument("username", help="Identifiant du compte (username).")
        parser.add_argument(
            "--site", default="http://localhost:8000", help="Adresse du serveur de développement."
        )

    def handle(self, *args, username, site, **options):
        if not dev_login.enabled():
            raise CommandError(
                "Refusé : cette commande ne marche qu'en développement (DEBUG). "
                "En production, la connexion se fait par clé d'accès."
            )
        try:
            person = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f"Aucun compte « {username} ».") from None
        if not person.is_active:
            raise CommandError("Ce compte est désactivé.")
        self.stdout.write("Lien de connexion (10 minutes, une seule fois) :")
        self.stdout.write(dev_login.make_link(person, site))
