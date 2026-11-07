from django.apps import AppConfig


class HousingConfig(AppConfig):
    name = "housing"
    verbose_name = "Logement"

    def ready(self):
        from . import checks  # noqa: F401 (registers the checks)
