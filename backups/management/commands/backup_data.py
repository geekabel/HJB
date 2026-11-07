"""Back up the database and the photos, then read the backup back (card T37).

    python manage.py backup_data --to /var/backups/hjb --keep 14

Run it once a day. A backup that fails its check is reported (exit code 1)
and the older ones are kept.
"""

from django.core.management.base import BaseCommand, CommandError

from backups import service


class Command(BaseCommand):
    help = "Sauvegarde la base et les photos, puis relit la sauvegarde."

    def add_arguments(self, parser):
        parser.add_argument("--to", required=True, help="Dossier des sauvegardes.")
        parser.add_argument(
            "--keep",
            type=int,
            default=14,
            help="Nombre de sauvegardes gardées (14 par défaut). Les plus anciennes partent.",
        )

    def handle(self, *args, to, keep, **options):
        if keep < 1:
            raise CommandError("--keep doit valoir au moins 1.")
        try:
            folder = service.make(to)
            manifest = service.verify(folder)
        except service.BackupError as error:
            raise CommandError(f"Sauvegarde ratée : {error}") from error
        self.stdout.write(
            f"Sauvegarde vérifiée : {folder} ({service.describe(manifest)}). "
            f"Base copiée : {manifest['database']}."
        )
        for name in service.prune(to, keep):
            self.stdout.write(f"Ancienne sauvegarde supprimée : {name}")
