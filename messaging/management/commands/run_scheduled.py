from django.core.management.base import BaseCommand

from messaging.sending import run_due


class Command(BaseCommand):
    help = (
        "Lance les messages et les relances arrivés à l'heure, reprend les envois "
        "interrompus et enregistre les départs prévus. À lancer chaque minute (voir le README)."
    )

    def handle(self, *args, **options):
        counts = run_due()
        if any(counts.values()):
            self.stdout.write(
                f"Messages : {counts['messages']}. Relances : {counts['reminders']}. "
                f"Reprises : {counts['resumed']}. Départs : {counts['departures']}."
            )
