from django.apps import AppConfig


class SmsConfig(AppConfig):
    name = "sms"
    verbose_name = "SMS"

    def ready(self):
        from . import checks  # noqa: F401  (enregistre les contrôles)
