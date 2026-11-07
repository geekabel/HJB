"""Configuration checks of the wifi encryption (python manage.py check).

Django docs: https://docs.djangoproject.com/en/6.1/topics/checks/
"""

from django.core.checks import Error, Tags, register
from django.core.exceptions import ImproperlyConfigured


@register(Tags.security)
def wifi_encryption_keys(app_configs, **kwargs):
    from .wifi_crypto import _fernet

    try:
        _fernet()
    except ImproperlyConfigured as error:
        return [
            Error(
                str(error),
                hint="Régler DJANGO_WIFI_KEYS (voir .env.example).",
                id="housing.E001",
            )
        ]
    return []
