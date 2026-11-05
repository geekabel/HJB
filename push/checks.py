"""Configuration checks for Web Push (python manage.py check)."""

from django.conf import settings
from django.core.checks import Error, register
from django.core.exceptions import ImproperlyConfigured

from .vapid import vapid


@register()
def vapid_settings(app_configs, **kwargs):
    errors = []
    try:
        vapid()
    except ImproperlyConfigured as error:
        errors.append(
            Error(
                f"Clé VAPID absente ou invalide : {error}",
                hint="Créer une clé avec « python manage.py vapid_key » (voir .env.example).",
                id="push.E001",
            )
        )
    contact = settings.VAPID_CONTACT
    if not contact.startswith(("mailto:", "https://")):
        errors.append(
            Error(
                "Le contact VAPID doit commencer par « mailto: » ou « https:// ».",
                hint="Remplir DJANGO_VAPID_CONTACT (voir .env.example).",
                id="push.E002",
            )
        )
    return errors
