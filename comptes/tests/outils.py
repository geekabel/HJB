"""Aides pour les tests : créer un compte avec ses rôles."""

from comptes.models import User
from comptes.roles import definir_roles


def creer_utilisateur(username, *roles, **champs):
    utilisateur = User.objects.create_user(username=username, **champs)
    if roles:
        definir_roles(utilisateur, roles)
    # Relire depuis la base : les permissions sont mises en cache sur l'objet.
    return User.objects.get(pk=utilisateur.pk)
