from django.contrib.auth.models import Group, Permission
from django.test import TestCase

from comptes.models import User
from comptes.roles import (
    GROUPE_MODERATEURS,
    GROUPES_GERES,
    PERMISSIONS,
    PERMISSIONS_PAR_GROUPE,
    Role,
    installer_groupes,
)


def recharger(utilisateur):
    # Doc Django : les permissions sont mises en cache sur l'objet ; on le relit.
    return User.objects.get(pk=utilisateur.pk)


# Droits attendus par rôle (lecture humaine de roles.py).
ATTENDU = {
    Role.RESIDENT: set(),
    Role.ACCUEIL: {
        "acceder_espace_equipe",
        "gerer_residents",
        "generer_code_activation",
        "envoyer_messages",
        "gerer_signalements",
    },
    Role.EDUCATEUR: {"acceder_espace_equipe", "envoyer_messages", "gerer_rendezvous"},
    Role.MAINTENANCE: {"acceder_espace_equipe", "envoyer_messages", "gerer_signalements"},
    Role.ADMIN: set(PERMISSIONS),
}


class GroupesInstallesTests(TestCase):
    def test_groupes_crees_par_migrate(self):
        noms = set(Group.objects.values_list("name", flat=True))
        self.assertTrue(set(GROUPES_GERES) <= noms)

    def test_permissions_des_groupes(self):
        for nom, codes in PERMISSIONS_PAR_GROUPE.items():
            with self.subTest(groupe=nom):
                groupe = Group.objects.get(name=nom)
                self.assertEqual(
                    set(groupe.permissions.values_list("codename", flat=True)), set(codes)
                )

    def test_installation_sans_effet_si_deja_faite(self):
        avant = (Group.objects.count(), Permission.objects.count())
        installer_groupes()
        self.assertEqual((Group.objects.count(), Permission.objects.count()), avant)

    def test_le_code_corrige_une_permission_ajoutee_a_la_main(self):
        groupe = Group.objects.get(name="Maintenance")
        groupe.permissions.add(Permission.objects.get(codename="voir_code_wifi"))
        installer_groupes()
        self.assertFalse(groupe.permissions.filter(codename="voir_code_wifi").exists())


class DroitsParRoleTests(TestCase):
    def test_chaque_role_a_exactement_ses_droits(self):
        for role, codes in ATTENDU.items():
            with self.subTest(role=role):
                utilisateur = recharger(User.objects.create_user(username=role.lower(), role=role))
                for code in PERMISSIONS:
                    self.assertEqual(
                        utilisateur.has_perm(f"comptes.{code}"),
                        code in codes,
                        f"{role} / {code}",
                    )

    def test_est_equipe(self):
        self.assertFalse(User(role=Role.RESIDENT).est_equipe)
        for role in (Role.ACCUEIL, Role.EDUCATEUR, Role.MAINTENANCE, Role.ADMIN):
            self.assertTrue(User(role=role).est_equipe)

    def test_changer_de_role_change_de_groupe(self):
        utilisateur = User.objects.create_user(username="marc", role=Role.MAINTENANCE)
        utilisateur.role = Role.ACCUEIL
        utilisateur.save()
        self.assertEqual(list(utilisateur.groups.values_list("name", flat=True)), ["Accueil"])
        self.assertTrue(recharger(utilisateur).has_perm("comptes.gerer_residents"))

    def test_retour_au_role_resident_retire_tous_les_droits(self):
        utilisateur = User.objects.create_user(username="ines", role=Role.ACCUEIL)
        utilisateur.role = Role.RESIDENT
        utilisateur.save()
        self.assertFalse(utilisateur.groups.exists())
        self.assertFalse(recharger(utilisateur).has_perm("comptes.acceder_espace_equipe"))

    def test_moderateur_designe_parmi_les_residents(self):
        utilisateur = User.objects.create_user(username="yanis")
        utilisateur.est_moderateur = True
        utilisateur.save(update_fields=["est_moderateur"])
        utilisateur = recharger(utilisateur)
        self.assertTrue(utilisateur.has_perm("comptes.moderer_discussion"))
        self.assertFalse(utilisateur.has_perm("comptes.acceder_espace_equipe"))
        self.assertTrue(utilisateur.groups.filter(name=GROUPE_MODERATEURS).exists())

    def test_derniere_connexion_ne_touche_pas_aux_groupes(self):
        utilisateur = User.objects.create_user(username="sam", role=Role.EDUCATEUR)
        with self.assertNumQueries(1):
            utilisateur.save(update_fields=["last_login"])

    def test_super_utilisateur_en_ligne_de_commande(self):
        admin = User.objects.create_superuser(username="admin", password="mot-de-passe-test")
        self.assertEqual(admin.role, Role.ADMIN)
        self.assertTrue(admin.groups.filter(name="Administration").exists())
