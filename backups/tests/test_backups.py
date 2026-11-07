"""Backups are made, read back, restored and rotated (card T37)."""

import json
import shutil
import sqlite3
import tarfile
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import TransactionTestCase, override_settings

from accounts.models import User
from accounts.tests.helpers import make_user
from backups import service


class BackupTests(TransactionTestCase):
    # A copy made inside an open transaction would wait for its lock: the
    # real command never runs inside one.

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.media = self.dir / "media"
        (self.media / "reports").mkdir(parents=True)
        (self.media / "reports" / "a.jpg").write_bytes(b"photo")
        self.target = self.dir / "backups"
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        make_user("ines", first_name="Inès")

    def test_backup_restores_the_data(self):
        folder = service.make(self.target)
        manifest = service.verify(folder)
        self.assertEqual(manifest["files"], ["reports/a.jpg"])
        self.assertEqual(oct(folder.stat().st_mode & 0o777), "0o700")
        # Restore: the copy is a working database with the same rows.
        copy = sqlite3.connect(folder / service.DB_NAME)
        names = [row[0] for row in copy.execute("SELECT username FROM accounts_user")]
        copy.close()
        self.assertEqual(names, list(User.objects.values_list("username", flat=True)))
        with tarfile.open(folder / service.MEDIA_NAME) as archive:
            restored = self.dir / "restored"
            archive.extractall(restored, filter="data")
        self.assertEqual((restored / "reports" / "a.jpg").read_bytes(), b"photo")

    def test_a_changed_backup_is_refused(self):
        folder = service.make(self.target)
        with open(folder / service.DB_NAME, "r+b") as database:
            database.seek(200)
            database.write(b"\x00\xff" * 50)
        with self.assertRaisesMessage(service.BackupError, "fichier absent ou modifié"):
            service.verify(folder)

    def test_a_backup_that_does_not_match_its_manifest(self):
        folder = service.make(self.target)
        manifest = json.loads((folder / service.MANIFEST).read_text())
        manifest["rows"]["accounts_user"] += 1
        (folder / service.MANIFEST).write_text(json.dumps(manifest))
        with self.assertRaisesMessage(service.BackupError, "nombre de lignes"):
            service.verify(folder)

    def test_command_keeps_the_last_ones(self):
        self.target.mkdir()
        for name in ("hjb-20260101-030000", "hjb-20260102-030000", "notes"):
            (self.target / name).mkdir()
        out = StringIO()
        call_command("backup_data", "--to", str(self.target), "--keep", "2", stdout=out)
        self.assertIn("Sauvegarde vérifiée", out.getvalue())
        left = sorted(p.name for p in self.target.iterdir())
        self.assertEqual(len(left), 3)
        self.assertIn("hjb-20260102-030000", left)
        self.assertIn("notes", left)  # not a backup: never deleted
        self.assertNotIn("hjb-20260101-030000", left)
        newest = sorted(n for n in left if n.startswith("hjb-"))[-1]
        out = StringIO()
        call_command("verify_backup", str(self.target / newest), stdout=out)
        self.assertIn("Sauvegarde valide", out.getvalue())

    def test_verify_command_reports_a_bad_folder(self):
        with self.assertRaisesMessage(CommandError, "Sauvegarde invalide"):
            call_command("verify_backup", str(self.dir))
