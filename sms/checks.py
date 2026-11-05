"""System checks ("manage.py check") for the SMS setting.

Django docs: https://docs.djangoproject.com/en/6.1/topics/checks/
"""

from django.conf import settings
from django.core.checks import Error, Warning, register

TEST_PROVIDERS = ("DisabledProvider", "ConsoleProvider", "MemoryProvider")
MIN_SECRET_LENGTH = 32


@register("sms")
def check_sms_setting(app_configs, **kwargs):
    from .providers.base import ConfigurationError
    from .service import active_provider

    try:
        provider = active_provider()
    except ConfigurationError as error:
        return [Error(str(error), hint="Voir le réglage SMS.", id="sms.E001")]
    missing = provider.missing_options()
    if missing:
        return [
            Error(
                f"Fournisseur SMS « {provider.name} » : options manquantes ({', '.join(missing)}).",
                hint="Remplir les variables d'environnement correspondantes (.env.example).",
                id="sms.E002",
            )
        ]
    return []


@register("sms")
def check_receipt_secret(app_configs, **kwargs):
    secret = getattr(settings, "SMS_RECEIPT_SECRET", "")
    if secret and len(secret) < MIN_SECRET_LENGTH:
        return [
            Error(
                "DJANGO_SMS_RECEIPT_SECRET est trop court "
                f"({MIN_SECRET_LENGTH} caractères au moins).",
                hint="Il protège l'adresse des accusés de réception : voir .env.example.",
                id="sms.E003",
            )
        ]
    return []


@register("sms", deploy=True)
def check_production_provider(app_configs, **kwargs):
    class_name = getattr(settings, "SMS", {}).get("BACKEND", "").rsplit(".", 1)[-1]
    if class_name in TEST_PROVIDERS:
        return [
            Warning(
                "Les SMS ne partent pas : aucun fournisseur réel n'est configuré.",
                hint="Régler DJANGO_SMS_PROVIDER sur « ovh » (ou « smsgate » pour des essais).",
                id="sms.W001",
            )
        ]
    if class_name == "OvhProvider" and not getattr(settings, "SMS_RECEIPT_SECRET", ""):
        return [
            Warning(
                "Pas d'accusés de réception des SMS : DJANGO_SMS_RECEIPT_SECRET est vide.",
                hint="Voir .env.example et le README (adresse de rappel OVHcloud).",
                id="sms.W002",
            )
        ]
    return []
