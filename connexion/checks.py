"""Contrôles de configuration de la connexion (python manage.py check --deploy).

Doc Django : https://docs.djangoproject.com/en/6.1/topics/checks/
"""

from django.conf import settings
from django.core.checks import Tags, Warning, register


@register(Tags.security, deploy=True)
def adresse_administration(app_configs, **kwargs):
    if settings.ADMIN_URL.strip("/") == "admin":
        return [
            Warning(
                "L'administration est à l'adresse /admin/, la plus visée par les robots.",
                hint="Choisir une autre adresse avec DJANGO_ADMIN_URL (voir .env.example).",
                id="connexion.W001",
            )
        ]
    return []
