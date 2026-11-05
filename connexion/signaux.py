"""Réactions aux départs et aux suppressions de clés d'accès.

Doc Django : signaux de modèle (post_delete) et transaction.on_commit
https://docs.djangoproject.com/en/6.1/ref/signals/#post-delete
https://docs.djangoproject.com/en/6.1/topics/db/transactions/#performing-actions-after-commit
"""

from django.db import transaction
from django_otp_webauthn.utils import get_credential_model

from comptes.sessions import fermer_toutes


def retirer_cles_au_depart(sender, resident, **kwargs):
    """Appelé dans la transaction du départ. Le nombre de clés va au journal."""
    cles = get_credential_model().objects.filter(user=resident)
    nombre = cles.count()
    cles.delete()
    return {"cles_retirees": nombre}


def fermer_sessions_apres_suppression(sender, instance, **kwargs):
    """Une clé supprimée (administration, téléphone perdu, départ) ferme les sessions du compte.

    Sinon, l'appareil perdu resterait connecté jusqu'à la fin de sa session :
    la session ne dépend pas de la clé. On ferme après la validation de la
    transaction, pour ne rien fermer si la suppression est annulée.
    """
    identifiant = instance.user_id  # le compte lui-même est peut-être en cours de suppression
    transaction.on_commit(lambda: fermer_toutes(identifiant))
