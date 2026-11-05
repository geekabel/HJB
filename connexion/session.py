"""Durée des sessions et confirmation récente par clé d'accès (carte T13).

- Un résident connecté par clé d'accès garde sa session 90 jours sans
  activité : il utilise surtout son propre téléphone.
- Le personnel garde la durée par défaut (SESSION_COOKIE_AGE, 12 heures).
- Les actions sensibles (code wifi, ajout d'une clé…) demandent une
  vérification par clé d'accès de moins de 10 minutes : une session longue
  sur un téléphone volé ne suffit pas.

Doc Django : https://docs.djangoproject.com/en/6.1/topics/http/sessions/#django.contrib.sessions.backends.base.SessionBase.set_expiry
"""

import time
from datetime import timedelta

from django.conf import settings

DUREE_RESIDENT = timedelta(days=90)
FENETRE_CONFIRMATION = timedelta(minutes=10)
CLE_CONFIRMEE = "connexion_confirmee_le"


def est_resident(utilisateur):
    """Même règle que User.objects.residents() : aucun rôle ni accès du personnel."""
    return not (utilisateur.is_staff or utilisateur.is_superuser or utilisateur.est_equipe)


def ouvrir(request, utilisateur):
    """À appeler après chaque vérification réussie par clé d'accès."""
    duree = (
        DUREE_RESIDENT
        if est_resident(utilisateur)
        else timedelta(seconds=settings.SESSION_COOKIE_AGE)
    )
    request.session.set_expiry(int(duree.total_seconds()))
    request.session[CLE_CONFIRMEE] = time.time()


def confirmee_recemment(request):
    """Vrai si la clé d'accès a servi il y a moins de 10 minutes dans cette session."""
    moment = request.session.get(CLE_CONFIRMEE)
    if not isinstance(moment, (int, float)):
        return False
    return 0 <= time.time() - moment < FENETRE_CONFIRMATION.total_seconds()
