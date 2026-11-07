"""Delete the personal data past its time (card T36).

    python manage.py purge_personal_data            # counts only
    python manage.py purge_personal_data --apply    # deletes

The durations are residence settings (page "Réglages"). Once they are
validated by the association, run it once a day with --apply.
"""

from django.core.management.base import BaseCommand

from privacy import retention


class Command(BaseCommand):
    help = "Supprime les données personnelles dont la durée de conservation est passée."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Supprime vraiment. Sans cette option, la commande compte seulement.",
        )

    def handle(self, *args, apply=False, **options):
        result = retention.run(apply=apply)
        text = retention.describe(result.counts()) or "rien"
        if apply:
            self.stdout.write(f"Supprimé : {text}.")
        else:
            self.stdout.write(f"À supprimer : {text}. Rien n'est supprimé sans --apply.")
