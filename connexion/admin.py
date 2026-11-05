"""Clés d'accès dans l'administration : lecture et suppression seulement.

Supprimer une clé coupe l'accès de l'appareil (téléphone perdu, par exemple) :
la clé ne sert plus, et les sessions ouvertes du compte sont fermées
(connexion/signaux.py).
La bibliothèque fournit la classe d'administration sans l'enregistrer.
"""

from django.contrib import admin
from django_otp_webauthn.admin import WebAuthnCredentialAdmin
from django_otp_webauthn.utils import get_credential_model


@admin.register(get_credential_model())
class CleAccesAdmin(WebAuthnCredentialAdmin):
    def has_change_permission(self, request, obj=None):
        return False
