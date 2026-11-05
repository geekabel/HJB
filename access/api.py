"""JSON endpoints for passkey login (card T13).

We reuse the django-otp-webauthn views, as its docs suggest:
https://django-otp-webauthn.readthedocs.io/en/stable/how_to_guides/customize_views.html

Three changes:
- user verification (Face ID, fingerprint, phone PIN) is always required,
  even to confirm a person who is already logged in;
- after verification, the session gets its length and the time of the
  confirmation (access/session_policy.py);
- login begins are rate limited per IP address (access/rate_limits.py, T14).
"""

from django.http import JsonResponse
from django_otp_webauthn.views import (
    BeginCredentialAuthenticationView,
    CompleteCredentialAuthenticationView,
)

from audit.service import client_ip

from . import rate_limits, session_policy
from .errors import FrenchErrorsMixin, error_response

TOO_MANY_ATTEMPTS = "Trop de tentatives depuis ce réseau. Réessayez dans quelques minutes."


class VerifyBeginView(FrenchErrorsMixin, BeginCredentialAuthenticationView):
    def dispatch(self, request, *args, **kwargs):
        ip = client_ip(request)
        if rate_limits.limit_reached("begin", ip, rate_limits.MAX_BEGINS):
            return error_response("too_many_attempts", 429, TOO_MANY_ATTEMPTS)
        rate_limits.record_attempt("begin", ip, rate_limits.BEGIN_WINDOW)
        return super().dispatch(request, *args, **kwargs)

    def post(self, *args, **kwargs):
        user = self.get_user()
        options, state = self.get_helper().authenticate_begin(
            user=user, require_user_verification=True
        )
        self.request.session["otp_webauthn_authentication_state"] = state
        return JsonResponse(options)


class VerifyCompleteView(FrenchErrorsMixin, CompleteCredentialAuthenticationView):
    def complete_auth(self, device):
        # Log the person in if needed (WebAuthn backend, new session key),
        # then record the verified device (django-otp).
        super().complete_auth(device)
        session_policy.open_session(self.request, device.user)
