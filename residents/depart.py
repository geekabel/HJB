"""Départ d'un résident : fin du séjour, compte désactivé, sessions fermées, trace.

Docs Django :
- signaux : https://docs.djangoproject.com/en/6.1/topics/signals/#defining-and-sending-signals
- sessions en base : https://docs.djangoproject.com/en/6.1/topics/http/sessions/#using-database-backed-sessions
- un compte inactif est refusé par ModelBackend (user_can_authenticate) :
  https://docs.djangoproject.com/en/6.1/ref/contrib/auth/#django.contrib.auth.backends.ModelBackend
"""

from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.models import Session
from django.core.exceptions import ValidationError
from django.db import transaction
from django.dispatch import Signal
from django.utils import timezone

from journal.models import Action
from journal.service import journaliser
from logement.services import sejour_en_cours

# Envoyé pendant la transaction du départ, avec resident, sejour (ou None) et le.
# Les cartes T13 (clés d'accès) et T15 (wifi) s'y branchent pour couper leurs accès :
# si l'un d'eux échoue, le départ entier est annulé.
depart_enregistre = Signal()


def fermer_sessions(utilisateur):
    """Supprime les sessions ouvertes de cet utilisateur. Renvoie leur nombre."""
    identifiant = str(utilisateur.pk)
    fermees = 0
    for session in Session.objects.filter(expire_date__gt=timezone.now()).iterator():
        if session.get_decoded().get(SESSION_KEY) == identifiant:
            session.delete()
            fermees += 1
    return fermees


def verifier_date(le, sejour):
    """Erreurs possibles sur la date de départ, en clair."""
    if le > timezone.localdate():
        raise ValidationError(
            "La date ne peut pas être dans le futur. Enregistrez le départ le jour même.",
            code="depart_futur",
        )
    if sejour and le < sejour.arrivee:
        raise ValidationError(
            f"La date est avant l'arrivée dans la chambre ({sejour.arrivee:%d/%m/%Y}).",
            code="depart_avant_arrivee",
        )


@transaction.atomic
def enregistrer_depart(resident, le, *, requete=None):
    """Enregistre le départ. Tout ou rien. Renvoie le séjour terminé (ou None)."""
    sejour = sejour_en_cours(resident)
    verifier_date(le, sejour)
    if sejour:
        sejour.depart = le
        sejour.full_clean()
        sejour.save(update_fields=["depart"])

    resident.is_active = False
    # Change aussi l'empreinte de session : toute session restante devient invalide.
    resident.set_unusable_password()
    resident.save(update_fields=["is_active", "password"])

    depart_enregistre.send(sender=resident.__class__, resident=resident, sejour=sejour, le=le)
    sessions = fermer_sessions(resident)
    journaliser(
        Action.DEPART_RESIDENT,
        cible=resident,
        details={
            "chambre": sejour.chambre.numero if sejour else "",
            "depart": le.isoformat(),
            "sessions_fermees": sessions,
        },
        requete=requete,
    )
    return sejour
