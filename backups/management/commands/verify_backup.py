"""Read a backup back and check it (card T37).

python manage.py verify_backup /var/backups/hjb/hjb-20261107-030000
"""

from django.core.management.base import BaseCommand, CommandError

from backups import service


class Command(BaseCommand):
    help = "Relit une sauvegarde et vérifie qu'elle est complète."

    def add_arguments(self, parser):
        parser.add_argument("folder", help="Dossier d'une sauvegarde.")
        parser.add_argument(
            "--restore",
            action="store_true",
            help="PostgreSQL : restaure aussi dans une base jetable, puis la supprime.",
        )

    def handle(self, *args, folder, restore=False, **options):
        try:
            manifest = service.verify(folder, restore=restore)
        except service.BackupError as error:
            raise CommandError(f"Sauvegarde invalide : {error}") from error
        self.stdout.write(
            f"Sauvegarde valide, faite le {manifest['made_at']} : {service.describe(manifest)}."
        )
        if "restored_users" in manifest:
            self.stdout.write(
                f"Restauration d'essai réussie : {manifest['restored_users']} comptes."
            )
