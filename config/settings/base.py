"""Réglages communs à tous les environnements.

Les fichiers ``dev.py`` et ``prod.py`` importent ce module puis ajoutent
leurs propres valeurs. Le module actif est choisi par la variable
d'environnement ``DJANGO_SETTINGS_MODULE``.

Documentation :
https://docs.djangoproject.com/en/6.1/topics/settings/
https://docs.djangoproject.com/en/6.1/ref/settings/
"""

import os
from pathlib import Path

from django.contrib.messages import constants as niveaux
from django.core.exceptions import ImproperlyConfigured

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
    "sms",
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


# SMS : fournisseur interchangeable (application sms, carte T10).
# DJANGO_SMS_FOURNISSEUR : console (rien n'est envoyé), smsgate, ovh ou aucun.
# Les identifiants viennent toujours de l'environnement (voir .env.example).

FOURNISSEURS_SMS = {
    "aucun": ("sms.fournisseurs.aucun.FournisseurAucun", {}),
    "console": ("sms.fournisseurs.console.FournisseurConsole", {}),
    "smsgate": (
        "sms.fournisseurs.smsgate.FournisseurSmsGate",
        {
            "url": "SMSGATE_URL",
            "jeton": "SMSGATE_JETON",
            "identifiant": "SMSGATE_IDENTIFIANT",
            "mot_de_passe": "SMSGATE_MOT_DE_PASSE",
            "sim": "SMSGATE_SIM",
        },
    ),
    "ovh": (
        "sms.fournisseurs.ovh.FournisseurOvh",
        {
            "endpoint": "OVH_ENDPOINT",
            "service": "OVH_SMS_SERVICE",
            "application_key": "OVH_APPLICATION_KEY",
            "application_secret": "OVH_APPLICATION_SECRET",
            "consumer_key": "OVH_CONSUMER_KEY",
            "expediteur": "OVH_SMS_EXPEDITEUR",
        },
    ),
}


def reglage_sms(par_defaut):
    """Réglage SMS lu dans l'environnement. ``par_defaut`` : console ou aucun."""
    choix = os.environ.get("DJANGO_SMS_FOURNISSEUR") or par_defaut
    if choix not in FOURNISSEURS_SMS:
        raise ImproperlyConfigured(
            f"DJANGO_SMS_FOURNISSEUR={choix!r} : valeurs possibles {', '.join(FOURNISSEURS_SMS)}."
        )
    classe, variables = FOURNISSEURS_SMS[choix]
    return {
        "BACKEND": classe,
        "OPTIONS": {cle: os.environ.get(variable, "") for cle, variable in variables.items()},
    }


# En développement, la console affiche les SMS. La production refuse d'envoyer
# tant qu'aucun fournisseur n'est choisi (voir prod.py).
SMS = reglage_sms("console")

# Tests : aucun vrai SMS, voir outils/lanceur_tests.py.
TEST_RUNNER = "outils.lanceur_tests.LanceurTests"
