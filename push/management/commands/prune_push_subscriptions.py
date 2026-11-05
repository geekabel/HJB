from django.core.management.base import BaseCommand

from push.services import prune


class Command(BaseCommand):
    help = "Supprime les appareils des comptes désactivés et ceux qui échouent trop souvent."

    def handle(self, *args, **options):
        count = prune()
        s = "s" if count > 1 else ""
        self.stdout.write(f"{count} appareil{s} supprimé{s}.")
