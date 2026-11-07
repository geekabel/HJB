"""Configuration checks for login and access (python manage.py check --deploy).

Django docs: https://docs.djangoproject.com/en/6.1/topics/checks/
"""

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register

# First path segments already used by the app: the admin site must not hide
# them (and the staff area middleware would loop on /connexion/).
RESERVED_SEGMENTS = {
    "",
    "connexion",
    "compte",
    "activer",
    "equipe",
    "guide",
    "wifi",
    "hors-ligne",
    "installer",
    "notifications",
    "messages",
    "r",
    "dev",
    "sms",
    "rendez-vous",
    "manifest.webmanifest",
    "sw.js",
    "favicon.ico",
    "static",
    "media",
}


@register(Tags.security, Tags.urls)
def admin_url_not_taken(app_configs, **kwargs):
    first = settings.ADMIN_URL.strip("/").split("/")[0]
    if first in RESERVED_SEGMENTS:
        return [
            Error(
                f"L'adresse de l'administration « {settings.ADMIN_URL} » est déjà prise.",
                hint="Choisir une autre valeur pour DJANGO_ADMIN_URL (voir .env.example).",
                id="access.E001",
            )
        ]
    return []


@register(Tags.security, deploy=True)
def admin_url_not_default(app_configs, **kwargs):
    if settings.ADMIN_URL.strip("/") == "admin":
        return [
            Warning(
                "L'administration est à l'adresse /admin/, la plus visée par les robots.",
                hint="Choisir une autre adresse avec DJANGO_ADMIN_URL (voir .env.example).",
                id="access.W001",
            )
        ]
    return []
