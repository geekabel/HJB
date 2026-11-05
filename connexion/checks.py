"""Contrôles de configuration de la connexion (python manage.py check --deploy).

Doc Django : https://docs.djangoproject.com/en/6.1/topics/checks/
"""

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register

# Premiers segments déjà pris par l'application : l'administration ne doit pas
# les masquer (et le middleware de l'équipe tournerait en boucle sur /connexion/).
ADRESSES_RESERVEES = {"", "connexion", "activer", "equipe", "guide", "static", "media"}


@register(Tags.security, Tags.urls)
def adresse_administration_libre(app_configs, **kwargs):
    premier = settings.ADMIN_URL.strip("/").split("/")[0]
    if premier in ADRESSES_RESERVEES:
        return [
            Error(
                f"L'adresse de l'administration « {settings.ADMIN_URL} » est déjà prise.",
                hint="Choisir une autre valeur pour DJANGO_ADMIN_URL (voir .env.example).",
                id="connexion.E001",
            )
        ]
    return []


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
