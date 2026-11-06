from django.apps import AppConfig


class ReportsConfig(AppConfig):
    name = "reports"
    verbose_name = "Signalements"

    def ready(self):
        from . import signals  # noqa: F401  (photo files go with their row)
