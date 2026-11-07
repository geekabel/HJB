"""Roles, groups and permissions.

A role is a Django group. A person can have several roles
(for example Front desk and Maintenance): their rights are then the sum of
the rights of their groups. A resident is an account with no staff role.

The code is the source of truth: on each ``migrate``, the groups
get exactly the permissions listed here. Django creates its permissions
in the ``post_migrate`` signal, so after the migrations
(docs: "Permissions and Authorization"). The groups are therefore created at
the same moment, in a ``post_migrate`` handler.
"""

from django.apps import apps as global_apps
from django.db import models


class Role(models.TextChoices):
    FRONT_DESK = "front_desk", "Accueil"
    EDUCATOR = "educator", "Éducateur"
    MAINTENANCE = "maintenance", "Maintenance"
    ADMIN = "admin", "Administration"
    # Given by the staff to a staff member or to a resident.
    MODERATOR = "moderator", "Modérateur"


STAFF_ROLES = frozenset({Role.FRONT_DESK, Role.EDUCATOR, Role.MAINTENANCE, Role.ADMIN})

GROUP_BY_ROLE = {
    Role.FRONT_DESK: "Accueil",
    Role.EDUCATOR: "Éducateurs",
    Role.MAINTENANCE: "Maintenance",
    Role.ADMIN: "Administration",
    Role.MODERATOR: "Modérateurs",
}
ROLE_BY_GROUP = {group: role for role, group in GROUP_BY_ROLE.items()}

# Project permissions, declared in User.Meta.permissions.
PERMISSIONS = {
    "access_staff_area": "Peut accéder à l'espace équipe",
    "view_residents": "Peut consulter la liste et les fiches des résidents",
    "manage_residents": "Peut gérer les résidents et leurs séjours",
    "issue_activation_codes": "Peut générer un code d'activation",
    "view_wifi_password": "Peut afficher un mot de passe wifi",
    "manage_wifi_settings": "Peut changer le format des accès wifi",
    "send_messages": "Peut envoyer des messages aux résidents",
    "manage_reports": "Peut traiter les signalements",
    "manage_appointments": "Peut gérer ses disponibilités et ses rendez-vous",
    "moderate_discussion": "Peut modérer la discussion entre résidents",
    "view_audit_log": "Peut consulter le journal d'audit",
    "manage_roles": "Peut changer les rôles d'un utilisateur",
    "manage_settings": "Peut changer les réglages de la résidence",
}

PERMISSIONS_BY_ROLE = {
    Role.FRONT_DESK: [
        "access_staff_area",
        "view_residents",
        "manage_residents",
        "issue_activation_codes",
        "send_messages",
        "manage_reports",
    ],
    Role.EDUCATOR: [
        "access_staff_area",
        # Educators can view residents, but not change them.
        "view_residents",
        "send_messages",
        "manage_appointments",
    ],
    Role.MAINTENANCE: [
        "access_staff_area",
        "send_messages",
        "manage_reports",
    ],
    Role.ADMIN: list(PERMISSIONS),
    Role.MODERATOR: ["moderate_discussion"],
}


def install_groups(apps=global_apps, using="default"):
    """Create or update the groups and their permissions. No effect if already done."""
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")

    user_type, _ = ContentType.objects.db_manager(using).get_or_create(
        app_label="accounts", model="user"
    )
    permissions = {}
    for codename, label in PERMISSIONS.items():
        permission, _ = Permission.objects.db_manager(using).get_or_create(
            content_type=user_type, codename=codename, defaults={"name": label}
        )
        permissions[codename] = permission

    for role, codenames in PERMISSIONS_BY_ROLE.items():
        group, _ = Group.objects.db_manager(using).get_or_create(name=GROUP_BY_ROLE[role])
        group.permissions.set([permissions[codename] for codename in codenames])


def create_groups_after_migrate(sender, apps=global_apps, using="default", **kwargs):
    """post_migrate signal handler (connected in AccountsConfig.ready)."""
    install_groups(apps=apps, using=using)


def roles_of(user):
    """Roles of a user, read from their groups (benefits from a prefetch_related)."""
    if user.pk is None:
        return set()
    return {ROLE_BY_GROUP[g.name] for g in user.groups.all() if g.name in ROLE_BY_GROUP}


def set_roles(user, roles):
    """Give the user exactly these roles. Return (roles before, roles after).

    Groups that are not roles are left alone.
    """
    from django.contrib.auth.models import Group

    wanted = {Role(r) for r in roles}
    before = roles_of(user)
    groups = {g.name: g for g in Group.objects.filter(name__in=GROUP_BY_ROLE.values())}
    user.groups.remove(*[groups[GROUP_BY_ROLE[r]] for r in before - wanted])
    user.groups.add(*[groups[GROUP_BY_ROLE[r]] for r in wanted - before])
    # Django docs: permissions stay cached on this object. To check them
    # right away, reload the user from the database.
    return before, wanted
