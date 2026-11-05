"""Départ d'un résident : fin du séjour, compte désactivé, sessions fermées, trace.

Docs Django :
- signaux : https://docs.djangoproject.com/en/6.1/topics/signals/#defining-and-sending-signals
- sessions en base : https://docs.djangoproject.com/en/6.1/topics/http/sessions/#using-database-backed-sessions
- un compte inactif est refusé par ModelBackend (user_can_authenticate) :
  https://docs.djangoproject.com/en/6.1/ref/contrib/auth/#django.contrib.auth.backends.ModelBackend
"""

from importlib import import_module

from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.models import Session
from django.core.exceptions import ValidationError
from django.db import transaction
from django.dispatch import Signal
from django.utils import timezone

from comptes.models import CodeActivation
from journal.models import Action
from journal.service import journaliser
from logement.services import sejour_en_cours

# Envoyé pendant la transaction du départ, avec resident, sejour (ou None) et le.
# Les cartes T13 (clés d'accès) et T15 (wifi) s'y branchent pour couper leurs accès :
# si l'un d'eux échoue, le départ entier est annulé.
depart_enregistre = Signal()


def cles_de_session(utilisateur):
    """Clés des sessions ouvertes de cet utilisateur.

    Lit la table des sessions : vaut pour les moteurs « db » (réglage actuel)
    et « cached_db ». Avec un autre moteur, il faudra revoir cette fonction ;
    le changement d'empreinte du mot de passe ferme de toute façon les
    sessions restantes à leur prochaine requête.
    """
    identifiant = str(utilisateur.pk)
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


def est_parti(resident):
    """Compte désactivé et plus de séjour en cours : le départ est déjà fait.

    Un compte désactivé ailleurs (administration) mais encore logé peut
    toujours recevoir son départ, pour libérer la chambre.
    """
    return not resident.is_active and sejour_en_cours(resident) is None


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


def enregistrer_depart(resident, le, *, requete=None):
    """Enregistre le départ. Tout ou rien. Renvoie le séjour terminé (ou None)."""
    # Lecture des sessions avant la transaction : elle peut être longue et
    # n'a pas besoin du verrou d'écriture.
    cles = cles_de_session(resident)
    with transaction.atomic():
        # Verrou sur la ligne : deux départs, ou un départ et une modification
        # de fiche, ne peuvent pas se croiser.
        resident = type(resident).objects.select_for_update().get(pk=resident.pk)
        if est_parti(resident):
            raise ValidationError(
                "Le départ de cette personne est déjà enregistré.", code="deja_parti"
            )
        sejour = sejour_en_cours(resident)
        verifier_date(le, sejour)
        if sejour:
            sejour.depart = le
            sejour.full_clean()
            sejour.save(update_fields=["depart"])

        # Un code d'activation encore valide ne doit plus servir.
        CodeActivation.objects.valides().filter(utilisateur=resident).update(
            annule_le=timezone.now()
        )
        resident.is_active = False
        # Change aussi l'empreinte de session : toute session restante devient invalide.
        resident.set_unusable_password()
        resident.save(update_fields=["is_active", "password"])

        depart_enregistre.send(sender=resident.__class__, resident=resident, sejour=sejour, le=le)
        sessions = fermer_sessions(cles)
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


def enregistrer_retour(resident, chambre, le, *, requete=None):
    """Retour d'un ancien résident : compte réactivé et nouveau séjour. Tout ou rien.

    La personne devra ensuite recevoir un nouveau code d'activation à l'accueil.
    """
    from logement.services import affecter_chambre

    with transaction.atomic():
        resident = type(resident).objects.select_for_update().get(pk=resident.pk)
        if not est_parti(resident):
            raise ValidationError("Cette personne n'est pas partie.", code="pas_parti")
        if le > timezone.localdate():
            raise ValidationError("La date ne peut pas être dans le futur.", code="retour_futur")
        resident.is_active = True
        resident.save(update_fields=["is_active"])
        sejour = affecter_chambre(resident, chambre, le)
        journaliser(
            Action.RETOUR_RESIDENT,
            cible=resident,
            details={"chambre": chambre.numero, "arrivee": le.isoformat()},
            requete=requete,
        )
    return sejour
