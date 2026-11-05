"""Points d'entrée JSON de la connexion par clé d'accès (carte T13).

On reprend les vues de django-otp-webauthn, comme le prévoit sa doc :
https://django-otp-webauthn.readthedocs.io/en/stable/how_to_guides/customize_views.html

Deux changements :
- la vérification de l'utilisateur (Face ID, empreinte, code du téléphone)
  est toujours exigée, même pour confirmer une personne déjà connectée ;
- après la vérification, la session reçoit sa durée et l'heure de la
  confirmation (connexion/session.py).
"""

from django.http import JsonResponse
from django_otp_webauthn.views import (
    BeginCredentialAuthenticationView,
    CompleteCredentialAuthenticationView,
)

from . import session
from .erreurs import ErreursEnFrancais


class DebutVerification(ErreursEnFrancais, BeginCredentialAuthenticationView):
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
