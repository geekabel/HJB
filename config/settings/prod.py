"""Réglages de production.

Toutes les valeurs sensibles viennent de variables d'environnement
(voir ``.env.example``). Liste de contrôle suivie :
https://docs.djangoproject.com/en/6.1/howto/deployment/checklist/
"""

import os

from .base import *  # noqa: F403


def _liste(nom):
    """Lit une variable d'environnement « a,b,c » et renvoie une liste."""
    return [valeur.strip() for valeur in os.environ.get(nom, "").split(",") if valeur.strip()]


DEBUG = False

# Obligatoire : l'application refuse de démarrer sans clé.
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
SECRET_KEY_FALLBACKS = _liste("DJANGO_SECRET_KEY_FALLBACKS")

ALLOWED_HOSTS = _liste("DJANGO_ALLOWED_HOSTS")


# Base de données : PostgreSQL si POSTGRES_DB est défini, sinon SQLite.
# Le choix final est fait en T38 (déploiement).
# https://docs.djangoproject.com/en/6.1/ref/databases/

if os.environ.get("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ["POSTGRES_DB"],
            "USER": os.environ.get("POSTGRES_USER", ""),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "HOST": os.environ.get("POSTGRES_HOST", ""),
            "PORT": os.environ.get("POSTGRES_PORT", ""),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.environ.get("DJANGO_SQLITE_PATH", BASE_DIR / "db.sqlite3"),  # noqa: F405
        }
    }


# E-mail : un vrai serveur SMTP en production (MAILERS, nouveau en 6.1).
# https://docs.djangoproject.com/en/6.1/ref/settings/#mailers

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
        "OPTIONS": {
            "host": os.environ.get("DJANGO_EMAIL_HOST", "localhost"),
            "port": int(os.environ.get("DJANGO_EMAIL_PORT", "587")),
            "username": os.environ.get("DJANGO_EMAIL_USER", ""),
            "password": os.environ.get("DJANGO_EMAIL_PASSWORD", ""),
            "use_tls": os.environ.get("DJANGO_EMAIL_USE_TLS", "1") == "1",
            "timeout": 10,
        },
    },
}
DEFAULT_FROM_EMAIL = os.environ.get("DJANGO_DEFAULT_FROM_EMAIL", "webmaster@localhost")
SERVER_EMAIL = DEFAULT_FROM_EMAIL


# SMS : sans DJANGO_SMS_FOURNISSEUR, aucun envoi, et rien d'écrit dans les
# journaux (la console y mettrait numéros et codes). Voir base.py.

SMS = reglage_sms("aucun")  # noqa: F405


# HTTPS
# https://docs.djangoproject.com/en/6.1/topics/security/#ssl-https

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# HSTS : on commence par une courte durée, puis on l'augmente une fois
# HTTPS vérifié (carte T37).
SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_SECURE_HSTS_SECONDS", "3600"))

# Ces deux réglages touchent tous les sous-domaines du domaine choisi.
# Ils restent désactivés tant que le domaine n'est pas connu (T37) :
# `check --deploy` affiche donc security.W005 et security.W021.
SECURE_HSTS_INCLUDE_SUBDOMAINS = os.environ.get("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS") == "1"
SECURE_HSTS_PRELOAD = os.environ.get("DJANGO_SECURE_HSTS_PRELOAD") == "1"

# À activer seulement derrière un proxy qui écrase cet en-tête.
if os.environ.get("DJANGO_BEHIND_PROXY") == "1":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
