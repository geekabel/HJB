"""Écrire dans le journal d'audit.

from journal.models import Action
from journal.service import journaliser

journaliser(Action.ROLES_MODIFIES, cible=utilisateur, details={...}, requete=request)
"""

from django.contrib.contenttypes.models import ContentType

from .models import EntreeJournal


def adresse_ip(requete):
    """Adresse du client vue par Django (REMOTE_ADDR, doc HttpRequest.META).

    Derrière un proxy, c'est l'adresse du proxy : le réglage est prévu au
    déploiement (carte T38). On ne lit jamais X-Forwarded-For ici, car un
    client peut l'inventer.
    """
    if requete is None:
        return None
    return requete.META.get("REMOTE_ADDR") or None


def _libelle(cible):
    """« Awa Koné (awa.kone) » pour un compte qui a un nom, sinon str(cible)."""
    nom = cible.get_full_name() if hasattr(cible, "get_full_name") else ""
    return f"{nom} ({cible.get_username()})" if nom else str(cible)


def journaliser(action, *, acteur=None, cible=None, details=None, requete=None):
    """Ajoute une entrée au journal et la renvoie.

    Sans ``acteur``, on prend l'utilisateur connecté de ``requete`` s'il y en a un.
    """
    if acteur is None and requete is not None and requete.user.is_authenticated:
        acteur = requete.user
    entree = EntreeJournal(
        action=action,
        acteur=acteur,
        acteur_libelle=acteur.get_username() if acteur else "",
        details=details or {},
        adresse_ip=adresse_ip(requete),
    )
    if cible is not None:
        entree.cible_type = ContentType.objects.get_for_model(cible)
        entree.cible_id = str(cible.pk)
        entree.cible_libelle = _libelle(cible)[:200]
    entree.save()
    return entree
