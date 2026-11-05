from django.apps import AppConfig


class ConnexionConfig(AppConfig):
    name = "connexion"
    verbose_name = "Connexion"

    def ready(self):
        # Au départ d'un résident (T09), ses clés d'accès sont supprimées.
        from django.db.models.signals import post_delete
        from django_otp_webauthn.utils import get_credential_model

        from residents.depart import depart_enregistre

        from . import checks  # noqa: F401 (enregistre les contrôles)
        from .signaux import fermer_sessions_apres_suppression, retirer_cles_au_depart

        depart_enregistre.connect(retirer_cles_au_depart, dispatch_uid="connexion.retirer_cles")
        # Une clé supprimée ferme les sessions de son compte.
        post_delete.connect(
            fermer_sessions_apres_suppression,
            sender=get_credential_model(),
            dispatch_uid="connexion.fermer_sessions",
        )
