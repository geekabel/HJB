"""État du parcours d'activation, gardé dans la session (pas encore connecté).

Après un code accepté, la session note la personne et l'heure de début.
Le parcours (téléphone, puis clé d'accès) doit être fini dans l'heure.
"""

import time

from comptes.models import User

CLE = "activation"
DUREE = 60 * 60  # secondes


def demarrer(request, utilisateur):
    # Nouvelle clé de session : rien ne reste d'une session antérieure (fixation).
    request.session.cycle_key()
    request.session[CLE] = {"utilisateur": utilisateur.pk, "debut": time.time()}


def personne_en_cours(request):
    """La personne dont l'activation est en cours, ou None (parcours absent ou expiré)."""
    donnees = request.session.get(CLE)
    if not donnees:
        return None
    if time.time() - donnees.get("debut", 0) > DUREE:
        del request.session[CLE]
        return None
    return User.objects.filter(pk=donnees["utilisateur"], is_active=True).first()


def terminer(request):
    request.session.pop(CLE, None)
