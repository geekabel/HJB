"""Permissions des rôles, sans connexion par mot de passe (carte T14).

ModelBackend fait deux choses : la connexion par mot de passe et les
permissions (groupes = rôles). On garde les permissions et on coupe la
connexion : authenticate() ne reconnaît plus personne. La connexion passe
par la clé d'accès (django_otp_webauthn.backends.WebAuthnBackend).

Doc Django : https://docs.djangoproject.com/en/6.1/topics/auth/customizing/#handling-authorization-in-custom-backends
"""

from django.contrib.auth.backends import ModelBackend


class PermissionsSansMotDePasse(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        return None
