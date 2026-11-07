import logging

from django.core.management.base import BaseCommand

from appointments import reminders
from messaging.receipts import poll
from messaging.sending import run_due
from reports import reminders as report_reminders

logger = logging.getLogger(__name__)

EMPTY_RUN = {"messages": 0, "reminders": 0, "resumed": 0, "late": 0, "departures": 0}


class Command(BaseCommand):
    help = (
        "Lance les messages et les relances arrivés à l'heure, reprend les envois "
        "interrompus, enregistre les départs prévus, demande les accusés de réception "
        "des SMS, envoie les rappels de rendez-vous, les retards et le récapitulatif "
        "des signalements. À lancer chaque minute (voir le README)."
    )

    def handle(self, *args, **options):
        # Each duty runs even when another one fails: an error in the messages
        # never holds back the reminders of the meetings.
        counts = dict(self._run("messages", run_due, EMPTY_RUN))
        counts["receipts"] = self._run("accusés de réception", poll, 0)
        counts["appointments"] = self._run("rappels de rendez-vous", reminders.send_due, 0)
        counts["reports"] = self._run(
            "retards et récapitulatif des signalements", report_reminders.send_due, 0
        )
        if any(counts.values()):
            self.stdout.write(
                f"Messages : {counts['messages']}. Relances : {counts['reminders']}. "
                f"Reprises : {counts['resumed']}. Départs : {counts['departures']}. "
                f"Accusés demandés : {counts['receipts']}. "
                f"Rappels de rendez-vous : {counts['appointments']}. "
                f"Signalements : {counts['reports']}."
            )

    def _run(self, name, duty, empty):
        try:
            return duty()
        except Exception:
            logger.exception("run_scheduled: %s failed", name)
            self.stderr.write(f"Échec : {name} (voir les journaux).")
            return empty
