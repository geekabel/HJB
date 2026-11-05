"""État du parcours d'activation, gardé dans la session (pas encore connecté).

Après un code accepté, la session note la personne, le code utilisé et
l'heure de début. Le parcours (téléphone, puis clé d'accès) doit être fini
dans l'heure. Il s'arrête aussi dès que l'accueil remet un nouveau code à la
personne (un code volé ne garde pas la main) ou si elle part.
"""

import time

from comptes.models import CodeActivation, User
from connexion.session import est_resident

CLE = "activation"
DUREE = 60 * 60  # secondes


def demarrer(request, code_activation):
    # Nouvelle clé de session : rien ne reste d'une session antérieure (fixation).
    request.session.cycle_key()
    request.session[CLE] = {
        "utilisateur": code_activation.utilisateur_id,
        "code": code_activation.pk,
        "debut": time.time(),
    }


def personne_en_cours(request):
    """La personne dont l'activation est en cours, ou None (parcours absent ou fini)."""
    donnees = request.session.get(CLE)
    if not donnees:
        return None
    personne = User.objects.filter(pk=donnees["utilisateur"], is_active=True).first()
    code = CodeActivation.objects.filter(pk=donnees.get("code")).first()
    remplace = (
        code is None
        or code.utilisateur_id != donnees["utilisateur"]
        or CodeActivation.objects.filter(
            utilisateur_id=donnees["utilisateur"], cree_le__gt=code.cree_le
        ).exists()
    )
    # Le code doit correspondre au compte : code de l'accueil pour un résident,
    # code d'un administrateur pour le personnel (carte T14). Un compte qui a
    # changé de statut depuis la remise du code s'arrête ici.
    mauvais_type = (
        personne is not None and code is not None and code.pour_personnel == est_resident(personne)
    )
    if (
        time.time() - donnees.get("debut", 0) > DUREE
        or personne is None
        or remplace
        or mauvais_type
    ):
        del request.session[CLE]
        return None
    return personne


def noter(request, cle, valeur):
    """Note une étape franchie (par exemple « telephone_verifie »)."""
    donnees = request.session[CLE]
    donnees[cle] = valeur
    request.session[CLE] = donnees  # réaffecté pour que la session soit enregistrée


def retirer(request, cle):
    """Retire une valeur du parcours et enregistre la session tout de suite.

    Sert à l'état de la création de clé : même si la suite échoue, il ne
    peut pas resservir (pas de rejeu).
    """
    donnees = request.session.get(CLE) or {}
    valeur = donnees.pop(cle, None)
    if CLE in request.session:
        request.session[CLE] = donnees
    request.session.save()
    return valeur


def etape_faite(request, cle):
    return bool(request.session.get(CLE, {}).get(cle))


def terminer(request):
    request.session.pop(CLE, None)
