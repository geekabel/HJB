"""Read a backup back and check it (card T37).

python manage.py verify_backup /var/backups/hjb/hjb-20261107-030000
"""

from django.core.management.base import BaseCommand, CommandError

from backups import service


class Command(BaseCommand):
    help = "Relit une sauvegarde et vérifie qu'elle est complète."

    def add_arguments(self, parser):
        parser.add_argument("folder", help="Dossier d'une sauvegarde.")

    def handle(self, *args, folder, **options):
        try:
            manifest = service.verify(folder)
        except service.BackupError as error:
            raise CommandError(f"Sauvegarde invalide : {error}") from error
        rows = sum(manifest["rows"].values())
        self.stdout.write(
            f"Sauvegarde valide, faite le {manifest['made_at']} : "
            f"{rows} lignes, {len(manifest['files'])} photos."
        )
