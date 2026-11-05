"""Encrypt every stored wifi password again with the first key (card T15).

To change the key: put the new key first in DJANGO_WIFI_KEYS (keep the old
one after it), run this command, then remove the old key.

    python manage.py rotate_wifi_keys

Docs: https://cryptography.io/en/latest/fernet/ (MultiFernet.rotate)
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from housing import wifi_crypto
from housing.models import WifiAccess


class Command(BaseCommand):
    help = "Chiffre de nouveau les mots de passe wifi avec la première clé de DJANGO_WIFI_KEYS."

    def handle(self, *args, **options):
        count = 0
        with transaction.atomic():
            for access in WifiAccess.objects.select_for_update().only("pk", "encrypted_password"):
                try:
                    access.encrypted_password = wifi_crypto.rotate(access.encrypted_password)
                except wifi_crypto.WifiDecryptionError as error:
                    raise CommandError(
                        f"Accès wifi {access.pk} illisible avec les clés actuelles : rien n'est "
                        "changé. Remettez l'ancienne clé dans DJANGO_WIFI_KEYS."
                    ) from error
                access.save(update_fields=["encrypted_password"])
                count += 1
        s = "s" if count > 1 else ""
        self.stdout.write(f"{count} mot{s} de passe chiffré{s} de nouveau.")
