"""Aides pour les tests : créer un compte avec ses rôles."""

from comptes.models import User
from comptes.roles import definir_roles


def creer_utilisateur(username, *roles, **champs):
    utilisateur = User.objects.create_user(username=username, **champs)
    if roles:
        definir_roles(utilisateur, roles)
    # Relire depuis la base : les permissions sont mises en cache sur l'objet.
    return User.objects.get(pk=utilisateur.pk)


def connecter(client, utilisateur):
    """Connecte ``utilisateur`` comme après une clé d'accès (session vérifiée, carte T14).

    L'espace équipe et l'administration exigent une session vérifiée par clé
    d'accès : force_login() seul ne suffit plus. On enregistre une clé factice
    (jamais utilisée pour signer) et on la note dans la session, comme le fait
    django_otp.login().
    """
    import os

    from django_otp import DEVICE_ID_SESSION_KEY
    from django_otp_webauthn.utils import get_credential_model

    client.force_login(utilisateur)
    cle = get_credential_model().objects.create(
        user=utilisateur,
        credential_id=os.urandom(16),
        public_key=b"cle-factice",
        aaguid="00000000-0000-0000-0000-000000000000",
    )
    session = client.session
    session[DEVICE_ID_SESSION_KEY] = cle.persistent_id
    session.save()
    return cle
