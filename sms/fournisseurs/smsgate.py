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
        if self.options.get("sim") and str(self.options["sim"]) not in {"1", "2", "3"}:
            manquantes.append("sim (1, 2 ou 3)")
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
        except requests.ConnectionError as erreur:
            # Connexion impossible (y compris délai de connexion) : rien n'est parti.
            raise ErreurEnvoi(
                f"SMSGate est injoignable ({type(erreur).__name__}).", temporaire=True
            ) from erreur
        except requests.RequestException as erreur:
            # Délai de réponse dépassé, réponse coupée : le SMS est peut-être parti.
            raise ErreurEnvoi(
                f"SMSGate n'a pas répondu à temps ({type(erreur).__name__}).", incertain=True
            ) from erreur

        donnees = _json(reponse)
        if 200 <= reponse.status_code < 300:
            if donnees.get("id"):
                return ResultatEnvoi(self.nom, str(donnees["id"]))
            raise ErreurEnvoi(
                "SMSGate a accepté le message sans donner son identifiant.", incertain=True
            )
        detail = donnees.get("message", "")
        raise ErreurEnvoi(
            f"SMSGate a refusé l'envoi (code {reponse.status_code}). {detail}".strip(),
            temporaire=reponse.status_code in CODES_TEMPORAIRES,
        )


def _json(reponse):
    """Le corps JSON s'il s'agit d'un objet, sinon un dictionnaire vide."""
    try:
        donnees = reponse.json()
    except ValueError:
        return {}
    return donnees if isinstance(donnees, dict) else {}
