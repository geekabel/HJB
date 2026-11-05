"""Points d'entrée JSON de la connexion par clé d'accès (carte T13).

On reprend les vues de django-otp-webauthn, comme le prévoit sa doc :
https://django-otp-webauthn.readthedocs.io/en/stable/how_to_guides/customize_views.html

Trois changements :
- la vérification de l'utilisateur (Face ID, empreinte, code du téléphone)
  est toujours exigée, même pour confirmer une personne déjà connectée ;
- après la vérification, la session reçoit sa durée et l'heure de la
  confirmation (connexion/session.py) ;
- les débuts de connexion sont limités par adresse IP (connexion/limites.py, T14).
"""

from django.http import JsonResponse
from django_otp_webauthn.views import (
    BeginCredentialAuthenticationView,
    CompleteCredentialAuthenticationView,
)

from journal.service import adresse_ip

from . import limites, session
from .erreurs import ErreursEnFrancais, reponse_erreur

TROP_D_ESSAIS = "Trop de tentatives depuis ce réseau. Réessayez dans quelques minutes."


class DebutVerification(ErreursEnFrancais, BeginCredentialAuthenticationView):
    def dispatch(self, request, *args, **kwargs):
        ip = adresse_ip(request)
        if limites.atteinte("debut", ip, limites.DEBUTS_MAX):
            return reponse_erreur("trop_d_essais", 429, TROP_D_ESSAIS)
        limites.noter("debut", ip, limites.FENETRE_DEBUTS)
        return super().dispatch(request, *args, **kwargs)

    def post(self, *args, **kwargs):
        utilisateur = self.get_user()
        options, etat = self.get_helper().authenticate_begin(
            user=utilisateur, require_user_verification=True
        )
        self.request.session["otp_webauthn_authentication_state"] = etat
        return JsonResponse(options)


class FinVerification(ErreursEnFrancais, CompleteCredentialAuthenticationView):
    def complete_auth(self, device):
        # Connecte la personne si besoin (backend WebAuthn, nouvelle clé de
        # session), puis note l'appareil vérifié (django-otp).
        super().complete_auth(device)
        session.ouvrir(self.request, device.user)
