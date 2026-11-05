"""Départ d'un résident : fin du séjour, compte désactivé, sessions fermées, trace.

Docs Django :
- signaux : https://docs.djangoproject.com/en/6.1/topics/signals/#defining-and-sending-signals
- sessions en base : https://docs.djangoproject.com/en/6.1/topics/http/sessions/#using-database-backed-sessions
- un compte inactif est refusé par ModelBackend (user_can_authenticate) :
  https://docs.djangoproject.com/en/6.1/ref/contrib/auth/#django.contrib.auth.backends.ModelBackend
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.dispatch import Signal
from django.utils import timezone

from comptes.models import CodeActivation
from comptes.sessions import cles_de_session, fermer_sessions
from journal.models import Action
from journal.service import journaliser
from logement.services import sejour_en_cours

# Envoyé pendant la transaction du départ, avec resident, sejour (ou None) et le.
# Les cartes T13 (clés d'accès, connexion/signaux.py) et T15 (wifi) s'y branchent :
# si l'un d'eux échoue, le départ entier est annulé.
depart_enregistre = Signal()


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

        # Chaque récepteur peut renvoyer un dict, ajouté aux détails du journal
        # (par exemple le nombre de clés d'accès supprimées).
        reponses = depart_enregistre.send(
            sender=resident.__class__, resident=resident, sejour=sejour, le=le
        )
        sessions = fermer_sessions(cles)
        details = {
            "chambre": sejour.chambre.numero if sejour else "",
            "depart": le.isoformat(),
            "sessions_fermees": sessions,
        }
        for _recepteur, reponse in reponses:
            if isinstance(reponse, dict):
                details.update(reponse)
        journaliser(Action.DEPART_RESIDENT, cible=resident, details=details, requete=requete)
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
        # Le compte doit être activé de nouveau (code, téléphone, clé d'accès) :
        # sans cela, il paraîtrait « activé » à cause de l'ancienne connexion.
        resident.last_login = None
        resident.telephone_verifie = ""
        resident.telephone_verifie_le = None
        resident.save(
            update_fields=["is_active", "last_login", "telephone_verifie", "telephone_verifie_le"]
        )
        # Aucune ancienne clé d'accès ne doit survivre au retour (elles sont
        # supprimées au départ ; ceci couvre une clé créée de justesse).
        from django_otp_webauthn.utils import get_credential_model

        get_credential_model().objects.filter(user=resident).delete()
        sejour = affecter_chambre(resident, chambre, le)
        journaliser(
            Action.RETOUR_RESIDENT,
            cible=resident,
            details={"chambre": chambre.numero, "arrivee": le.isoformat()},
            requete=requete,
        )
    return sejour
