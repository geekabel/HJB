"""SMSGate : un téléphone Android envoie les SMS (essais réels, peu de volume).

Doc : https://docs.sms-gate.app (API « 3rdparty », POST /3rdparty/v1/messages,
réponse 202 avec l'identifiant du message). Trois modes : serveur local sur le
téléphone (http://<ip-du-téléphone>:8080), nuage (https://api.sms-gate.app) ou
serveur privé. Authentification : jeton (nuage, privé) ou identifiant et mot de
passe affichés dans l'application (seule possibilité en mode local).
"""

import requests

from .base import ErreurEnvoi, FournisseurSms, ResultatEnvoi

# Codes après lesquels un nouvel essai plus tard peut réussir (doc SMSGate).
CODES_TEMPORAIRES = {429, 500, 502, 503, 504}


class FournisseurSmsGate(FournisseurSms):
    nom = "smsgate"
    options_obligatoires = ("url",)

    def options_manquantes(self):
        manquantes = super().options_manquantes()
        identifiants = self.options.get("identifiant") and self.options.get("mot_de_passe")
        if not (self.options.get("jeton") or identifiants):
            manquantes.append("jeton (ou identifiant et mot_de_passe)")
        return manquantes

    def envoyer(self, numero, texte):
        corps = {"textMessage": {"text": texte}, "phoneNumbers": [numero]}
        if self.options.get("sim"):
            corps["simNumber"] = int(self.options["sim"])
        en_tetes, auth = {}, None
        if self.options.get("jeton"):
            en_tetes["Authorization"] = f"Bearer {self.options['jeton']}"
        else:
            auth = (self.options["identifiant"], self.options["mot_de_passe"])
        url = self.options["url"].rstrip("/") + "/3rdparty/v1/messages"
        try:
            reponse = requests.post(
                url,
                json=corps,
                headers=en_tetes,
                auth=auth,
                timeout=float(self.options.get("delai", 10)),
            )
        except requests.RequestException as erreur:
            raise ErreurEnvoi(
                f"SMSGate est injoignable ({type(erreur).__name__}).", temporaire=True
            ) from erreur

        if 200 <= reponse.status_code < 300:
            try:
                return ResultatEnvoi(self.nom, str(reponse.json()["id"]))
            except (ValueError, KeyError) as erreur:
                raise ErreurEnvoi(
                    "SMSGate a répondu sans identifiant de message.", temporaire=True
                ) from erreur
        try:
            detail = reponse.json().get("message", "")
        except ValueError:
            detail = ""
        raise ErreurEnvoi(
            f"SMSGate a refusé l'envoi (code {reponse.status_code}). {detail}".strip(),
            temporaire=reponse.status_code in CODES_TEMPORAIRES,
        )
