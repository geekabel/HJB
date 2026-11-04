from django.apps import AppConfig
from django.db.models.signals import post_migrate


class ComptesConfig(AppConfig):
    name = "comptes"
    verbose_name = "Comptes"

    def ready(self):
        # Les groupes et leurs permissions sont (re)créés à la fin de chaque migrate.
        # Doc : signal post_migrate, branché dans ready() avec sender=self.
        from .roles import creer_groupes_apres_migration

        post_migrate.connect(creer_groupes_apres_migration, sender=self)
