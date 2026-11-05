"""Rôles, groupes et permissions.

Un rôle est un groupe Django. Une personne peut avoir plusieurs rôles
(par exemple Accueil et Maintenance) : ses droits sont alors la somme des
droits de ses groupes. Un résident est un compte sans rôle du personnel.

Le code est la source de vérité : à chaque ``migrate``, les groupes
reçoivent exactement les permissions listées ici. Les permissions de Django
sont créées par le signal ``post_migrate``, donc après les migrations
(doc : « Permissions and Authorization »). Les groupes sont donc créés au
même moment, dans un gestionnaire ``post_migrate``.
"""

from django.apps import apps as registre_global
from django.db import models


class Role(models.TextChoices):
    ACCUEIL = "ACCUEIL", "Accueil"
    EDUCATEUR = "EDUCATEUR", "Éducateur"
    MAINTENANCE = "MAINTENANCE", "Maintenance"
    ADMIN = "ADMIN", "Administration"
    # Donné par l'équipe à un membre du personnel ou à un résident.
    MODERATEUR = "MODERATEUR", "Modérateur"


ROLES_EQUIPE = frozenset({Role.ACCUEIL, Role.EDUCATEUR, Role.MAINTENANCE, Role.ADMIN})

GROUPE_PAR_ROLE = {
    Role.ACCUEIL: "Accueil",
    Role.EDUCATEUR: "Éducateurs",
    Role.MAINTENANCE: "Maintenance",
    Role.ADMIN: "Administration",
    Role.MODERATEUR: "Modérateurs",
}
ROLE_PAR_GROUPE = {groupe: role for role, groupe in GROUPE_PAR_ROLE.items()}

# Permissions propres au projet, déclarées dans User.Meta.permissions.
PERMISSIONS = {
    "acceder_espace_equipe": "Peut accéder à l'espace équipe",
    "gerer_residents": "Peut gérer les résidents et leurs séjours",
    "generer_code_activation": "Peut générer un code d'activation",
    "voir_code_wifi": "Peut afficher un mot de passe wifi",
    "envoyer_messages": "Peut envoyer des messages aux résidents",
    "gerer_signalements": "Peut traiter les signalements",
    "gerer_rendezvous": "Peut gérer ses disponibilités et ses rendez-vous",
    "moderer_discussion": "Peut modérer la discussion entre résidents",
    "voir_journal": "Peut consulter le journal d'audit",
    "gerer_roles": "Peut changer les rôles d'un utilisateur",
}

PERMISSIONS_PAR_ROLE = {
    Role.ACCUEIL: [
        "acceder_espace_equipe",
        "gerer_residents",
        "generer_code_activation",
        "envoyer_messages",
        "gerer_signalements",
    ],
    Role.EDUCATEUR: [
        "acceder_espace_equipe",
        "envoyer_messages",
        "gerer_rendezvous",
    ],
    Role.MAINTENANCE: [
        "acceder_espace_equipe",
        "envoyer_messages",
        "gerer_signalements",
    ],
    Role.ADMIN: list(PERMISSIONS),
    Role.MODERATEUR: ["moderer_discussion"],
}


def installer_groupes(apps=registre_global, using="default"):
    """Crée ou met à jour les groupes et leurs permissions. Sans effet si déjà fait."""
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")

    type_utilisateur, _ = ContentType.objects.db_manager(using).get_or_create(
        app_label="comptes", model="user"
    )
    permissions = {}
    for code, libelle in PERMISSIONS.items():
        permission, _ = Permission.objects.db_manager(using).get_or_create(
            content_type=type_utilisateur, codename=code, defaults={"name": libelle}
        )
        permissions[code] = permission

    for role, codes in PERMISSIONS_PAR_ROLE.items():
        groupe, _ = Group.objects.db_manager(using).get_or_create(name=GROUPE_PAR_ROLE[role])
        groupe.permissions.set([permissions[code] for code in codes])


def creer_groupes_apres_migration(sender, apps, using, **kwargs):
    """Gestionnaire du signal post_migrate (branché dans ComptesConfig.ready)."""
    installer_groupes(apps=apps, using=using)


def roles_de(utilisateur):
    """Rôles d'un utilisateur, lus dans ses groupes (profite d'un prefetch_related)."""
    if utilisateur.pk is None:
        return set()
    return {ROLE_PAR_GROUPE[g.name] for g in utilisateur.groups.all() if g.name in ROLE_PAR_GROUPE}


def definir_roles(utilisateur, roles):
    """Donne exactement ces rôles à l'utilisateur. Renvoie (rôles avant, rôles après).

    Les groupes qui ne sont pas des rôles ne sont pas touchés.
    """
    from django.contrib.auth.models import Group

    voulus = {Role(r) for r in roles}
    avant = roles_de(utilisateur)
    groupes = {g.name: g for g in Group.objects.filter(name__in=GROUPE_PAR_ROLE.values())}
    utilisateur.groups.remove(*[groupes[GROUPE_PAR_ROLE[r]] for r in avant - voulus])
    utilisateur.groups.add(*[groupes[GROUPE_PAR_ROLE[r]] for r in voulus - avant])
    # Doc Django : les permissions restent en cache sur cet objet ; pour les
    # vérifier tout de suite, relire l'utilisateur depuis la base.
    return avant, voulus
