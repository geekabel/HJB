from django.contrib.auth.models import Group, Permission
from django.test import TestCase

from accounts.models import User
from accounts.roles import (
    GROUP_BY_ROLE,
    PERMISSIONS,
    PERMISSIONS_BY_ROLE,
    Role,
    install_groups,
    set_roles,
)

from .helpers import make_user


def reload(user):
    # Django docs: permissions are cached on the object, so we read it again.
    return User.objects.get(pk=user.pk)


def rights(user):
    return {codename for codename in PERMISSIONS if user.has_perm(f"accounts.{codename}")}


# Expected rights for each role alone (human reading of roles.py).
EXPECTED = {
    Role.FRONT_DESK: {
        "access_staff_area",
        "view_residents",
        "manage_residents",
        "issue_activation_codes",
        "send_messages",
        "manage_reports",
    },
    Role.EDUCATOR: {
        "access_staff_area",
        "view_residents",
        "send_messages",
        "manage_appointments",
    },
    Role.MAINTENANCE: {"access_staff_area", "send_messages", "manage_reports"},
    Role.ADMIN: set(PERMISSIONS),
    Role.MODERATOR: {"moderate_discussion"},
}


class InstalledGroupsTests(TestCase):
    def test_one_group_per_role_created_by_migrate(self):
        names = set(Group.objects.values_list("name", flat=True))
        self.assertTrue(set(GROUP_BY_ROLE.values()) <= names)

    def test_group_permissions(self):
        for role, codenames in PERMISSIONS_BY_ROLE.items():
            with self.subTest(role=role):
                group = Group.objects.get(name=GROUP_BY_ROLE[role])
                self.assertEqual(
                    set(group.permissions.values_list("codename", flat=True)), set(codenames)
                )

    def test_install_has_no_effect_if_already_done(self):
        before = (Group.objects.count(), Permission.objects.count())
        install_groups()
        self.assertEqual((Group.objects.count(), Permission.objects.count()), before)

    def test_code_fixes_a_permission_added_by_hand(self):
        group = Group.objects.get(name="Maintenance")
        group.permissions.add(Permission.objects.get(codename="view_wifi_password"))
        install_groups()
        self.assertFalse(group.permissions.filter(codename="view_wifi_password").exists())


class RightsByRoleTests(TestCase):
    def test_resident_has_no_rights(self):
        resident = make_user("awa")
        self.assertEqual(resident.roles, set())
        self.assertFalse(resident.has_staff_role)
        self.assertEqual(rights(resident), set())

    def test_each_role_alone_has_exactly_its_rights(self):
        for role, codenames in EXPECTED.items():
            with self.subTest(role=role):
                self.assertEqual(rights(make_user(role.lower(), role)), codenames)

    def test_several_roles_add_up_rights(self):
        marc = make_user("marc", Role.FRONT_DESK, Role.MAINTENANCE)
        self.assertEqual(marc.roles, {Role.FRONT_DESK, Role.MAINTENANCE})
        self.assertEqual(rights(marc), EXPECTED[Role.FRONT_DESK] | EXPECTED[Role.MAINTENANCE])

    def test_has_staff_role(self):
        self.assertTrue(make_user("sam", Role.EDUCATOR).has_staff_role)
        # A resident moderator is not a staff member.
        self.assertFalse(make_user("yanis", Role.MODERATOR).has_staff_role)

    def test_roles_label(self):
        marie = make_user("marie", Role.MAINTENANCE, Role.FRONT_DESK)
        self.assertEqual(marie.roles_label, "Accueil, Maintenance")
        self.assertEqual(make_user("lina").roles_label, "Résident")

    def test_moderator_chosen_among_residents(self):
        yanis = make_user("yanis", Role.MODERATOR)
        self.assertEqual(rights(yanis), {"moderate_discussion"})

    def test_set_roles_replaces_and_returns_before_after(self):
        ines = make_user("ines", Role.FRONT_DESK, Role.MODERATOR)
        before, after = set_roles(ines, [Role.EDUCATOR])
        self.assertEqual(before, {Role.FRONT_DESK, Role.MODERATOR})
        self.assertEqual(after, {Role.EDUCATOR})
        ines = reload(ines)
        self.assertEqual(ines.roles, {Role.EDUCATOR})
        self.assertFalse(ines.has_perm("accounts.manage_residents"))

    def test_remove_all_roles(self):
        ines = make_user("ines", Role.FRONT_DESK)
        set_roles(ines, [])
        self.assertEqual(rights(reload(ines)), set())

    def test_other_groups_are_left_alone(self):
        other = Group.objects.create(name="Groupe hors rôles")
        ines = make_user("ines", Role.FRONT_DESK)
        ines.groups.add(other)
        set_roles(ines, [])
        self.assertEqual(list(ines.groups.all()), [other])

    def test_with_role(self):
        make_user("marc", Role.FRONT_DESK, Role.MAINTENANCE)
        make_user("sam", Role.MAINTENANCE)
        make_user("awa")
        names = set(User.objects.with_role(Role.MAINTENANCE).values_list("username", flat=True))
        self.assertEqual(names, {"marc", "sam"})

    def test_superuser_from_command_line(self):
        admin = User.objects.create_superuser(username="admin", password="test-password")
        self.assertEqual(reload(admin).roles, {Role.ADMIN})
