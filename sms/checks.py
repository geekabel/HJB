"""Contrôles « manage.py check » du réglage SMS.

Doc : https://docs.djangoproject.com/en/6.1/topics/checks/
"""

from django.conf import settings
from django.core.checks import Error, Warning, register

FOURNISSEURS_DE_TEST = ("FournisseurAucun", "FournisseurConsole", "FournisseurMemoire")


@register("sms")
def verifier_reglage_sms(app_configs, **kwargs):
    from .fournisseurs.base import ErreurConfiguration
    from .service import fournisseur_actif

    try:
        fournisseur = fournisseur_actif()
    except ErreurConfiguration as erreur:
        return [Error(str(erreur), hint="Voir le réglage SMS.", id="sms.E001")]
    manquantes = fournisseur.options_manquantes()
    if manquantes:
        return [
            Error(
                f"Fournisseur SMS « {fournisseur.nom} » : "
                f"options manquantes ({', '.join(manquantes)}).",
                hint="Remplir les variables d'environnement correspondantes (.env.example).",
                id="sms.E002",
            )
        ]
    return []


@register("sms", deploy=True)
def verifier_fournisseur_de_production(app_configs, **kwargs):
    nom_classe = getattr(settings, "SMS", {}).get("BACKEND", "").rsplit(".", 1)[-1]
    if nom_classe in FOURNISSEURS_DE_TEST:
        return [
            Warning(
                "Les SMS ne partent pas : aucun fournisseur réel n'est configuré.",
                hint="Régler DJANGO_SMS_FOURNISSEUR sur « ovh » (ou « smsgate » pour des essais).",
                id="sms.W001",
            )
        ]
    return []
