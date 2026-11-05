from django.apps import AppConfig


class ConnexionConfig(AppConfig):
    name = "connexion"
    verbose_name = "Connexion"

    def ready(self):
        # Au départ d'un résident (T09), ses clés d'accès sont supprimées.
        from residents.depart import depart_enregistre

        from .signaux import retirer_cles_au_depart

        depart_enregistre.connect(retirer_cles_au_depart, dispatch_uid="connexion.retirer_cles")
