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
    # Site d'administration réservé au personnel vérifié par clé d'accès (T14).
    "config.apps.AdminHJBConfig",
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
    "activation",
    "connexion",
    # Clés d'accès (carte T13) : django-otp et son extension WebAuthn.
    # https://django-otp-webauthn.readthedocs.io/en/stable/getting_started/quickstart.html
    "django_otp",
    "django_otp_webauthn",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Après AuthenticationMiddleware (doc de django-otp) : request.user.is_verified().
    "django_otp.middleware.OTPMiddleware",
    # Espace équipe et administration : personnel avec clé d'accès (T14).
    "connexion.middleware.EspaceEquipeMiddleware",
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

# Connexion par clé d'accès seulement (cartes T13 et T14) : aucun mot de passe,
# pour les résidents comme pour le personnel.
LOGIN_URL = "connexion:connexion"
LOGIN_REDIRECT_URL = "accueil"
AUTHENTICATION_BACKENDS = [
    "django_otp_webauthn.backends.WebAuthnBackend",
    # Permissions des rôles seulement : ce backend refuse tout mot de passe.
    "comptes.backends.PermissionsSansMotDePasse",
]

# Adresse de l'administration Django. En production, elle vient de
# DJANGO_ADMIN_URL (voir prod.py) : on évite l'adresse « admin/ », la plus visée.
ADMIN_URL = "admin/"

# Durée d'une session sans activité. Les résidents connectés par clé d'accès
# gardent la leur bien plus longtemps (voir connexion/session.py).
SESSION_COOKIE_AGE = 12 * 60 * 60
# La durée repart à chaque requête : c'est bien une durée « sans activité ».
SESSION_SAVE_EVERY_REQUEST = True

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


# Clés d'accès (passkeys), carte T13
# https://django-otp-webauthn.readthedocs.io/en/stable/getting_started/quickstart.html
# Le domaine (RP ID) et les origines autorisées dépendent de l'adresse du site :
# ils sont dans dev.py et prod.py. Changer de domaine rend les clés inutilisables.

OTP_WEBAUTHN_RP_NAME = "Habitat Jeunes Belfort"
OTP_WEBAUTHN_HELPER_CLASS = "connexion.webauthn.AideWebAuthn"
