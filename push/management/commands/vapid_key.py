from django.core.management.base import BaseCommand

from push.vapid import new_private_key


class Command(BaseCommand):
    help = "Affiche une nouvelle clé VAPID privée, à copier dans DJANGO_VAPID_PRIVATE_KEY."

    def handle(self, *args, **options):
        self.stdout.write(new_private_key())
        self.stderr.write(
            "Gardez-la secrète. Changer de clé oblige chaque appareil à réactiver "
            "les notifications."
        )
