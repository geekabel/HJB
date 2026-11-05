"""Sessions ouvertes d'un compte : les retrouver et les fermer.

Docs Django :
- sessions en base : https://docs.djangoproject.com/en/6.1/topics/http/sessions/#using-database-backed-sessions
"""

from importlib import import_module

from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.models import Session
from django.utils import timezone


def cles_de_session(utilisateur):
    """Clés des sessions ouvertes de cet utilisateur.

    Lit la table des sessions : vaut pour les moteurs « db » (réglage actuel)
    et « cached_db ». Avec un autre moteur, il faudra revoir cette fonction ;
    le changement d'empreinte du mot de passe ferme de toute façon les
    sessions restantes à leur prochaine requête.
    """
    identifiant = str(getattr(utilisateur, "pk", utilisateur))  # compte ou identifiant
    return [
        session.session_key
        for session in Session.objects.filter(expire_date__gt=timezone.now()).iterator()
        if session.get_decoded().get(SESSION_KEY) == identifiant
    ]


def fermer_sessions(cles):
    """Supprime ces sessions avec le moteur configuré (base et cache éventuel)."""
    moteur = import_module(settings.SESSION_ENGINE)
    for cle in cles:
        moteur.SessionStore(session_key=cle).delete()
    return len(cles)


def fermer_toutes(utilisateur, *, sauf=None):
    """Ferme toutes les sessions de ce compte, sauf la clé ``sauf``. Renvoie leur nombre."""
    return fermer_sessions([cle for cle in cles_de_session(utilisateur) if cle != sauf])
