"""Réglages communs à tous les environnements.

Les fichiers ``dev.py`` et ``prod.py`` importent ce module puis ajoutent
leurs propres valeurs. Le module actif est choisi par la variable
d'environnement ``DJANGO_SETTINGS_MODULE``.

Documentation :
https://docs.djangoproject.com/en/6.1/topics/settings/
https://docs.djangoproject.com/en/6.1/ref/settings/
"""

from pathlib import Path

from django.contrib.messages import constants as niveaux

# Racine du dépôt : config/settings/base.py -> trois niveaux au-dessus.
BASE_DIR = Path(__file__).resolve().parent.parent.parent


# Applications

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Applications du projet
    "comptes",
    "interface",
    "journal",
    "logement",
    "residents",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# Formulaires : gabarit de champ du système de design (interface/formulaires.py).
FORM_RENDERER = "interface.formulaires.RenduHJB"

WSGI_APPLICATION = "config.wsgi.application"


# Utilisateurs
# Modèle personnalisé, défini avant la première migration :
# https://docs.djangoproject.com/en/6.1/topics/auth/customizing/#using-a-custom-user-model-when-starting-a-project

# Provisoire : la page de connexion de l'administration, en attendant la
# connexion par clé d'accès (carte T13).
LOGIN_URL = "admin:login"

AUTH_USER_MODEL = "comptes.User"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Langue et fuseau horaire
# https://docs.djangoproject.com/en/6.1/topics/i18n/

LANGUAGE_CODE = "fr-fr"

TIME_ZONE = "Europe/Paris"

USE_I18N = True

USE_TZ = True


# Fichiers statiques
# https://docs.djangoproject.com/en/6.1/howto/static-files/

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"


# Messages : les niveaux prennent le nom des bandeaux du système de design
# (classes alerte--succes, alerte--info, alerte--attention).
# https://docs.djangoproject.com/en/6.1/ref/contrib/messages/#message-tags

MESSAGE_TAGS = {
    niveaux.DEBUG: "info",
    niveaux.INFO: "info",
    niveaux.SUCCESS: "succes",
    niveaux.WARNING: "attention",
    niveaux.ERROR: "attention",
}


# E-mail : affiché dans la console tant que le fournisseur n'est pas choisi.
# https://docs.djangoproject.com/en/6.1/topics/email/#topic-email-configuration

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.console.EmailBackend",
    },
}
