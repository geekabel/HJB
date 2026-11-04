"""Rôles, groupes et permissions.

Chaque rôle du personnel correspond à un groupe Django. Le groupe porte les
permissions ; l'utilisateur est placé dans le bon groupe à chaque
enregistrement (voir ``User.save``). Le code est la source de vérité : au
``migrate``, les groupes reçoivent exactement les permissions listées ici.

Les permissions de Django sont créées par le signal ``post_migrate``, donc
après les migrations (doc : « Permissions and Authorization »). Les groupes
sont donc créés au même moment, dans un gestionnaire ``post_migrate``.
"""

from django.apps import apps as registre_global
from django.db import models


class Role(models.TextChoices):
    RESIDENT = "RESIDENT", "Résident"
    ACCUEIL = "ACCUEIL", "Accueil"
    EDUCATEUR = "EDUCATEUR", "Éducateur"
    MAINTENANCE = "MAINTENANCE", "Maintenance"
    ADMIN = "ADMIN", "Administration"


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
    "gerer_roles": "Peut changer le rôle d'un utilisateur",
}

GROUPE_PAR_ROLE = {
    Role.ACCUEIL: "Accueil",
    Role.EDUCATEUR: "Éducateurs",
    Role.MAINTENANCE: "Maintenance",
    Role.ADMIN: "Administration",
}

# Donné par l'équipe à un membre du personnel ou à des résidents (phase 2).
GROUPE_MODERATEURS = "Modérateurs"

PERMISSIONS_PAR_GROUPE = {
    "Accueil": [
        "acceder_espace_equipe",
        "gerer_residents",
        "generer_code_activation",
        "envoyer_messages",
        "gerer_signalements",
    ],
    "Éducateurs": [
        "acceder_espace_equipe",
        "envoyer_messages",
        "gerer_rendezvous",
    ],
    "Maintenance": [
        "acceder_espace_equipe",
        "envoyer_messages",
        "gerer_signalements",
    ],
    "Administration": list(PERMISSIONS),
    GROUPE_MODERATEURS: ["moderer_discussion"],
}

GROUPES_GERES = list(PERMISSIONS_PAR_GROUPE)


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

    for nom, codes in PERMISSIONS_PAR_GROUPE.items():
        groupe, _ = Group.objects.db_manager(using).get_or_create(name=nom)
        groupe.permissions.set([permissions[code] for code in codes])


def creer_groupes_apres_migration(sender, apps, using, **kwargs):
    """Gestionnaire du signal post_migrate (branché dans ComptesConfig.ready)."""
    installer_groupes(apps=apps, using=using)


def groupes_attendus(utilisateur):
    """Noms des groupes gérés auxquels l'utilisateur doit appartenir."""
    noms = set()
    if utilisateur.role in GROUPE_PAR_ROLE:
        noms.add(GROUPE_PAR_ROLE[utilisateur.role])
    if utilisateur.est_moderateur:
        noms.add(GROUPE_MODERATEURS)
    return noms


def synchroniser_groupes(utilisateur):
    """Place l'utilisateur dans les groupes de son rôle, et le retire des autres."""
    from django.contrib.auth.models import Group

    attendus = groupes_attendus(utilisateur)
    geres = list(Group.objects.filter(name__in=GROUPES_GERES))
    utilisateur.groups.remove(*[g for g in geres if g.name not in attendus])
    utilisateur.groups.add(*[g for g in geres if g.name in attendus])
