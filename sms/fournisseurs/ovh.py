"""OVHcloud : fournisseur de production.

Docs :
- envoi par l'API : https://docs.ovhcloud.com/fr/guides/web-cloud/messaging/sms/sending-via-api-c.md
  (POST /sms/{serviceName}/jobs ; droits GET /sms/, GET /sms/*/jobs, POST /sms/*/jobs)
- signature des requêtes : faite par la bibliothèque officielle python-ovh,
  comme le conseille OVHcloud (https://github.com/ovh/python-ovh).

``noStopClause`` : nos messages sont des informations de service, pas de la
prospection. Sans cette option, OVHcloud ajoute « STOP » et bloque l'envoi
entre 20 h et 8 h (doc OVHcloud).
"""

from .base import ErreurConfiguration, ErreurEnvoi, FournisseurSms, ResultatEnvoi


class FournisseurOvh(FournisseurSms):
    nom = "ovh"
    options_obligatoires = ("service", "application_key", "application_secret", "consumer_key")

    def _client(self):
        import ovh

        try:
            return ovh.Client(
                endpoint=self.options.get("endpoint") or "ovh-eu",
                application_key=self.options["application_key"],
                application_secret=self.options["application_secret"],
                consumer_key=self.options["consumer_key"],
                timeout=float(self.options.get("delai", 10)),
            )
        except ovh.exceptions.APIError as erreur:  # région inconnue, clés incohérentes
            raise ErreurConfiguration(f"Configuration OVHcloud invalide : {erreur}") from erreur

    def envoyer(self, numero, texte):
        from ovh import exceptions

        corps = {
            "message": texte,
            "receivers": [numero],
            "charset": "UTF-8",
            "priority": "high",
            "noStopClause": True,
        }
        if self.options.get("expediteur"):
            corps["sender"] = self.options["expediteur"]
        else:
            # Numéro court d'OVHcloud, qui permet aussi de recevoir les réponses.
            corps["senderForResponse"] = True
        try:
            reponse = self._client().post(f"/sms/{self.options['service']}/jobs", **corps)
        except (
            exceptions.HTTPError,
            exceptions.NetworkError,
            exceptions.InvalidResponse,
        ) as erreur:
            raise ErreurEnvoi(f"OVHcloud est injoignable ({erreur}).", temporaire=True) from erreur
        except exceptions.APIError as erreur:
            statut = getattr(getattr(erreur, "response", None), "status_code", 0) or 0
            raise ErreurEnvoi(
                f"OVHcloud a refusé l'envoi : {erreur}", temporaire=statut >= 500
            ) from erreur

        if reponse.get("invalidReceivers") or not reponse.get("ids"):
            raise ErreurEnvoi("OVHcloud a refusé ce numéro.", temporaire=False)
        return ResultatEnvoi(self.nom, str(reponse["ids"][0]))
