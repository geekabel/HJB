from django.apps import AppConfig
from django.db.models.signals import post_migrate


class AccountsConfig(AppConfig):
    name = "accounts"
    verbose_name = "Comptes"

    def ready(self):
        # Groups and their permissions are (re)created at the end of each migrate.
        # Docs: post_migrate signal, connected in ready() with sender=self.
        from .roles import create_groups_after_migrate

        post_migrate.connect(create_groups_after_migrate, sender=self)
