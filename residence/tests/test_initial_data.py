"""First loading from a YAML file (card T38)."""

import tempfile
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.core.management import CommandError, call_command
from django.test import TestCase

from accounts.models import User
from accounts.roles import Role, roles_of
from accounts.tests.helpers import make_user
from housing.models import Floor, Room
from residence.models import ResidenceSettings

EXAMPLE = Path(settings.BASE_DIR) / "deploy" / "initial-data.example.yaml"


class InitialDataTests(TestCase):
    def load(self, *args, text=None):
        path = EXAMPLE
        if text is not None:
            handle = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
            handle.write(text)
            handle.close()
            self.addCleanup(Path(handle.name).unlink)
            path = handle.name
        out = StringIO()
        call_command("load_initial_data", str(path), *args, stdout=out)
        return out.getvalue()

    def test_an_existing_account_is_not_promoted(self):
        make_user("marie.exemple", Role.FRONT_DESK)
        out = self.load()
        marie = User.objects.get(username="marie.exemple")
        self.assertFalse(marie.is_staff or marie.is_superuser)
        self.assertEqual(roles_of(marie), {Role.FRONT_DESK})
        self.assertIn("site_admin n'est pas appliqué", out)

    def test_the_example_loads_once(self):
        out = self.load()
        self.assertEqual(Floor.objects.count(), 3)
        self.assertEqual(Room.objects.filter(floor__number=1).count(), 20)
        self.assertTrue(Room.objects.filter(number="001", floor__number=0).exists())
        marie = User.objects.get(username="marie.exemple")
        self.assertEqual(roles_of(marie), {Role.ADMIN})
        self.assertFalse(marie.has_usable_password())
        self.assertTrue(marie.is_staff and marie.is_superuser)  # site_admin: true
        paul = User.objects.get(username="paul.exemple")
        self.assertEqual(roles_of(paul), {Role.FRONT_DESK})
        self.assertFalse(paul.is_staff or paul.is_superuser)
        self.assertEqual(ResidenceSettings.load().emergency_phone, "")
        self.assertIn("activation_code marie.exemple", out)
        # Again: nothing new, nothing broken.
        out = self.load()
        self.assertIn("Créé : 0.", out)
        self.assertEqual(Floor.objects.count(), 3)

    def test_dry_run_keeps_nothing(self):
        out = self.load("--dry-run")
        self.assertIn("Serait créé", out)
        self.assertFalse(Floor.objects.exists())
        self.assertFalse(User.objects.filter(username="marie.exemple").exists())

    def test_settings_changed_on_the_page_win(self):
        ResidenceSettings.objects.update_or_create(
            pk=1, defaults={"emergency_phone": "03 84 11 11 11"}
        )
        self.load()
        self.assertEqual(ResidenceSettings.load().emergency_phone, "03 84 11 11 11")

    def test_a_floor_added_later_stays(self):
        Floor.objects.create(number=1, name="Premier", visit_order=7)
        self.load()
        floor = Floor.objects.get(number=1)
        self.assertEqual((floor.name, floor.visit_order), ("Premier", 7))

    def test_a_wrong_file_loads_nothing(self):
        cases = {
            "floors:\n  - number: 1\n    rooms: ['101', '101']\n": "en double",
            "floors:\n  - number: -1\n": "nombre entier",
            "floors:\n  - number: 1\n    rooms: ['120-101']\n": "plage",
            "staff:\n  - username: x\n    roles: [boss]\n": "rôles parmi",
            "staff:\n  - username: x\n    roles: [admin]\n    site_admin: 'yes'\n": "true ou false",
            "staff:\n  - username: x\n    roles: [front_desk]\n    site_admin: true\n": (
                "seulement avec le rôle admin"
            ),
            "staff:\n  - username: x\n    roles: [admin]\n    phone: '12'\n": "Vérifiez",
            "chambres: []\n": "Rubrique inconnue",
            "residence:\n  color: red\n": "réglage inconnu",
            "- a\n- b\n": "rubriques",
            "floors: [\n": "YAML invalide",
            "!!python/object/apply:os.system ['echo hi']\n": "YAML invalide",
            "floors:\n  - number: 0\n    rooms: [001, 010]\n": "entre guillemets",
            "floors:\n  - number: true\n": "nombre entier",
            "floors:\n  - number: 1\n    visit_order: abc\n": "visit_order",
            "floors:\n  - number: 1\n    name: " + "x" * 61 + "\n": "60 caractères",
            "residence: [a, b]\n": "residence",
            "floors: {a: 1}\n": "floors",
            "staff:\n  - username: x\n    roles: [{admin: 1}]\n": "rôles parmi",
            "staff:\n  - username: 'a b'\n    roles: [admin]\n": "lettres, chiffres",
        }
        for text, message in cases.items():
            with self.subTest(text=text), self.assertRaisesMessage(CommandError, message):
                self.load(text=text)
        self.assertFalse(Floor.objects.exists())

    def test_room_names_with_a_dash(self):
        self.load(text="floors:\n  - number: 2\n    rooms: ['201-203', '214a-1', '214B-2']\n")
        self.assertEqual(
            sorted(Room.objects.values_list("number", flat=True)),
            ["201", "202", "203", "214A-1", "214B-2"],
        )

    def test_a_room_already_on_another_floor(self):
        Room.objects.create(number="101", floor=Floor.objects.create(number=9))
        with self.assertRaisesMessage(CommandError, "déjà sur l'étage 9"):
            self.load()
        self.assertEqual(Floor.objects.count(), 1)  # all or nothing
