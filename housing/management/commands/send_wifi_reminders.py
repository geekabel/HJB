from django.core.management.base import BaseCommand

from housing.reminders import send_wifi_reminders


class Command(BaseCommand):
    help = (
        "Envoie le rappel de fin d'accès wifi aux résidents concernés. "
        "À lancer chaque jour (voir le README)."
    )

    def handle(self, *args, **options):
        result = send_wifi_reminders()
        self.stdout.write(
            f"Rappels envoyés : {result.sent}. Rappel désactivé : {result.reminder_off}. "
            f"Sans appareil joignable : {result.not_delivered}."
        )
