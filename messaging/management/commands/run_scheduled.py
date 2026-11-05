from django.core.management.base import BaseCommand

from appointments import reminders
from messaging.receipts import poll
from messaging.sending import run_due


class Command(BaseCommand):
    help = (
        "Lance les messages et les relances arrivés à l'heure, reprend les envois "
        "interrompus, enregistre les départs prévus et demande les accusés de réception "
        "des SMS et envoie les rappels de rendez-vous. À lancer chaque minute (voir le README)."
    )

    def handle(self, *args, **options):
        counts = run_due()
        counts["receipts"] = poll()
        counts["appointments"] = reminders.send_due()
        if any(counts.values()):
            self.stdout.write(
                f"Messages : {counts['messages']}. Relances : {counts['reminders']}. "
                f"Reprises : {counts['resumed']}. Départs : {counts['departures']}. "
                f"Accusés demandés : {counts['receipts']}. "
                f"Rappels de rendez-vous : {counts['appointments']}."
            )
