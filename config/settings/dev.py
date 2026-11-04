"""Réglages de développement, utilisés par défaut par ``manage.py``.

Ne jamais utiliser ces réglages en production.
https://docs.djangoproject.com/en/6.1/howto/deployment/checklist/
"""

import os

from .base import *  # noqa: F403

DEBUG = True

# Clé de développement uniquement. La production lit sa propre clé
# dans l'environnement (voir prod.py).
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-cle-de-developpement-a-ne-jamais-utiliser-en-production",  # gitleaks:allow
)

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",  # noqa: F405
    }
}
