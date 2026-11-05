"""Role permissions, without password login (card T14).

ModelBackend does two things: password login and permissions
(groups = roles). We keep the permissions and turn off the login:
authenticate() no longer recognizes anyone. Login goes through the
passkey (django_otp_webauthn.backends.WebAuthnBackend).

Django docs: https://docs.djangoproject.com/en/6.1/topics/auth/customizing/#handling-authorization-in-custom-backends
"""

from django.contrib.auth.backends import ModelBackend


class PermissionsOnlyBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        return None
