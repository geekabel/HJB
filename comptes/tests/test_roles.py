from django.contrib.auth.models import Group, Permission
from django.test import TestCase

from comptes.models import User
from comptes.roles import (
    GROUPE_PAR_ROLE,
    PERMISSIONS,
    PERMISSIONS_PAR_ROLE,
    Role,
    definir_roles,
    installer_groupes,
)

from .outils import creer_utilisateur


def recharger(utilisateur):
    # Doc Django : les permissions sont mises en cache sur l'objet ; on le relit.
    return User.objects.get(pk=utilisateur.pk)


def droits(utilisateur):
    return {code for code in PERMISSIONS if utilisateur.has_perm(f"comptes.{code}")}


# Droits attendus par rôle seul (lecture humaine de roles.py).
ATTENDU = {
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
    Role.MODERATEUR: {"moderer_discussion"},
}


class GroupesInstallesTests(TestCase):
    def test_un_groupe_par_role_cree_par_migrate(self):
        noms = set(Group.objects.values_list("name", flat=True))
        self.assertTrue(set(GROUPE_PAR_ROLE.values()) <= noms)

    def test_permissions_des_groupes(self):
        for role, codes in PERMISSIONS_PAR_ROLE.items():
            with self.subTest(role=role):
                groupe = Group.objects.get(name=GROUPE_PAR_ROLE[role])
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
    def test_resident_sans_aucun_droit(self):
        resident = creer_utilisateur("awa")
        self.assertEqual(resident.roles, set())
        self.assertFalse(resident.est_equipe)
        self.assertEqual(droits(resident), set())

    def test_chaque_role_seul_a_exactement_ses_droits(self):
        for role, codes in ATTENDU.items():
            with self.subTest(role=role):
                self.assertEqual(droits(creer_utilisateur(role.lower(), role)), codes)

    def test_plusieurs_roles_cumulent_les_droits(self):
        marc = creer_utilisateur("marc", Role.ACCUEIL, Role.MAINTENANCE)
        self.assertEqual(marc.roles, {Role.ACCUEIL, Role.MAINTENANCE})
        self.assertEqual(droits(marc), ATTENDU[Role.ACCUEIL] | ATTENDU[Role.MAINTENANCE])

    def test_est_equipe(self):
        self.assertTrue(creer_utilisateur("sam", Role.EDUCATEUR).est_equipe)
        # Un résident modérateur n'est pas un membre du personnel.
        self.assertFalse(creer_utilisateur("yanis", Role.MODERATEUR).est_equipe)

    def test_moderateur_designe_parmi_les_residents(self):
        yanis = creer_utilisateur("yanis", Role.MODERATEUR)
        self.assertEqual(droits(yanis), {"moderer_discussion"})

    def test_definir_roles_remplace_et_renvoie_avant_apres(self):
        ines = creer_utilisateur("ines", Role.ACCUEIL, Role.MODERATEUR)
        avant, apres = definir_roles(ines, [Role.EDUCATEUR])
        self.assertEqual(avant, {Role.ACCUEIL, Role.MODERATEUR})
        self.assertEqual(apres, {Role.EDUCATEUR})
        ines = recharger(ines)
        self.assertEqual(ines.roles, {Role.EDUCATEUR})
        self.assertFalse(ines.has_perm("comptes.gerer_residents"))

    def test_retirer_tous_les_roles(self):
        ines = creer_utilisateur("ines", Role.ACCUEIL)
        definir_roles(ines, [])
        self.assertEqual(droits(recharger(ines)), set())

    def test_les_autres_groupes_ne_sont_pas_touches(self):
        autre = Group.objects.create(name="Groupe hors rôles")
        ines = creer_utilisateur("ines", Role.ACCUEIL)
        ines.groups.add(autre)
        definir_roles(ines, [])
        self.assertEqual(list(ines.groups.all()), [autre])

    def test_avec_role(self):
        creer_utilisateur("marc", Role.ACCUEIL, Role.MAINTENANCE)
        creer_utilisateur("sam", Role.MAINTENANCE)
        creer_utilisateur("awa")
        noms = set(User.objects.avec_role(Role.MAINTENANCE).values_list("username", flat=True))
        self.assertEqual(noms, {"marc", "sam"})

    def test_super_utilisateur_en_ligne_de_commande(self):
        admin = User.objects.create_superuser(username="admin", password="mot-de-passe-test")
        self.assertEqual(recharger(admin).roles, {Role.ADMIN})
