"""Opérations sur les séjours, toujours validées par full_clean() avant l'écriture."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Sejour


def sejour_en_cours(resident):
    return resident.sejours.en_cours().select_related("chambre__etage").first()


@transaction.atomic
def affecter_chambre(resident, chambre, le=None):
    """Loge la personne dans cette chambre à partir du jour ``le`` (aujourd'hui par défaut).

    - Pas de séjour en cours : un séjour commence.
    - Séjour en cours dans une autre chambre : il se termine ce jour-là et un
      nouveau commence (déménagement interne).
    - Séjour commencé le jour même : on corrige simplement la chambre.
    Renvoie le séjour en cours.
    """
    le = le or timezone.localdate()
    actuel = sejour_en_cours(resident)
    if actuel is not None:
        if actuel.chambre_id == chambre.pk:
            return actuel
        if le < actuel.arrivee:
            raise ValidationError(
                {"arrivee": "La date est avant le début du séjour en cours."},
                code="date_avant_sejour",
            )
        if le == actuel.arrivee:
            actuel.chambre = chambre
            actuel.full_clean()
            actuel.save()
            return actuel
        actuel.depart = le
        actuel.full_clean()
        actuel.save()
    nouveau = Sejour(resident=resident, chambre=chambre, arrivee=le)
    nouveau.full_clean()
    nouveau.save()
    return nouveau
