"""Load the residence, its floors and rooms, and the first staff accounts
from a YAML file, on a new server (card T38). See residence/initial_data.py."""

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from residence import initial_data


class Command(BaseCommand):
    help = "Charge la résidence, ses étages et chambres, et les premiers comptes de l'équipe."

    def add_arguments(self, parser):
        parser.add_argument(
            "path", help="Fichier YAML (modèle : deploy/initial-data.example.yaml)."
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Montre ce qui serait créé, sans rien garder.",
        )

    def handle(self, *args, path, dry_run=False, **options):
        try:
            plan = initial_data.read(path)
            report = initial_data.apply(plan, dry_run=dry_run)
        except (initial_data.DataError, ValidationError) as error:
            raise CommandError(f"Rien n'est chargé. {error}") from error
        verb = "Serait créé" if dry_run else "Créé"
        self.stdout.write(f"{verb} : {len(report.created)}. Déjà là : {len(report.kept)}.")
        for item in report.created:
            self.stdout.write(f"  + {item}")
        for item in report.kept:
            if "(" in item:  # kept, with something left undone
                self.stdout.write(f"  = {item}")
        if not dry_run:
            for person in plan.staff:
                if f"compte {person['username']}" in report.created:
                    self.stdout.write(
                        f"Code d'activation : python manage.py activation_code {person['username']}"
                    )
