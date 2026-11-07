"""Backups of the database and of the report photos (card T37).

A backup is a folder named after its time, for example
``hjb-20261107-0300``, with:

- ``db.sqlite3``: a copy made by SQLite's backup API, consistent even while
  the site, the worker and run_scheduled write
  (https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup);
- ``media.tar.gz``: the photo files (MEDIA_ROOT);
- ``manifest.json``: rows per table, files, and a SHA-256 of both archives.

``verify`` opens the copy and checks it against the manifest: a backup is
only a backup once it has been read back. With PostgreSQL (card T38), the
database part is pg_dump: the README says how.

What a backup does not hold, on purpose (card T37 review):
- the keys (SECRET_KEY, wifi keys, VAPID): they stay in the server's
  environment and are kept apart, so a stolen backup cannot open the wifi
  passwords;
- the sessions: a stolen backup must not log anyone in;
- the secrets of the staff app codes (TOTP): with them, anyone could
  compute the codes. After a restore, the staff link their app again.
The copy is then vacuumed: deleted rows leave no trace in free pages.
"""

import hashlib
import json
import shutil
import sqlite3
import tarfile
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.utils import timezone

PREFIX = "hjb-"
DB_NAME = "db.sqlite3"
MEDIA_NAME = "media.tar.gz"
MANIFEST = "manifest.json"
# Emptied in the copy: live logins, and the secrets of the staff app codes
# (with the lock that points to each of them).
LEFT_OUT = ("django_session", "access_appcodeguard", "otp_totp_totpdevice")


class BackupError(Exception):
    """The backup cannot be made, or does not match its manifest."""


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _row_counts(database):
    tables = [
        name
        for (name,) in database.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    return {
        table: database.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        for table in sorted(tables)
    }


def make(target_dir, now=None):
    """Write a new backup folder in ``target_dir`` and return its path."""
    if connection.vendor != "sqlite":
        raise BackupError("Base PostgreSQL : utilisez pg_dump (voir le README).")
    now = timezone.localtime(now)
    folder = Path(target_dir) / f"{PREFIX}{now:%Y%m%d-%H%M%S}"
    folder.mkdir(parents=True, exist_ok=False)
    folder.chmod(0o700)  # personal data: the owner only

    connection.ensure_connection()
    copy = sqlite3.connect(folder / DB_NAME)
    try:
        connection.connection.backup(copy)
        tables = {name for (name,) in copy.execute("SELECT name FROM sqlite_master")}
        for table in LEFT_OUT:
            if table in tables:
                copy.execute(f'DELETE FROM "{table}"')
        copy.commit()
        copy.execute("VACUUM")
        counts = _row_counts(copy)
    finally:
        copy.close()

    media_root = Path(settings.MEDIA_ROOT)
    files = []
    with tarfile.open(folder / MEDIA_NAME, "w:gz") as archive:
        if media_root.is_dir():
            for path in sorted(p for p in media_root.rglob("*") if p.is_file()):
                name = path.relative_to(media_root).as_posix()
                archive.add(path, arcname=name)
                files.append(name)

    manifest = {
        "made_at": now.isoformat(),
        # Which database was copied: a cron line without the production
        # settings would back up the development one (README).
        "database": str(connection.settings_dict["NAME"]),
        "left_out": list(LEFT_OUT),
        "rows": counts,
        "files": files,
        "sha256": {name: _sha256(folder / name) for name in (DB_NAME, MEDIA_NAME)},
    }
    (folder / MANIFEST).write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    for path in folder.iterdir():
        path.chmod(0o600)
    return folder


def verify(folder):
    """Read a backup back. Return its manifest; raise BackupError if wrong."""
    folder = Path(folder)
    try:
        manifest = json.loads((folder / MANIFEST).read_text())
    except (OSError, ValueError) as error:
        raise BackupError(f"Manifeste illisible : {error}") from error
    for name, expected in manifest["sha256"].items():
        if not (folder / name).is_file() or _sha256(folder / name) != expected:
            raise BackupError(f"{name} : fichier absent ou modifié.")
    database = sqlite3.connect(f"file:{folder / DB_NAME}?mode=ro", uri=True)
    try:
        status = database.execute("PRAGMA integrity_check").fetchone()[0]
        if status != "ok":
            raise BackupError(f"Base abîmée : {status}")
        if _row_counts(database) != manifest["rows"]:
            raise BackupError("Le nombre de lignes ne correspond pas au manifeste.")
    except sqlite3.DatabaseError as error:
        raise BackupError(f"Base illisible : {error}") from error
    finally:
        database.close()
    try:
        with tarfile.open(folder / MEDIA_NAME, "r:gz") as archive:
            names = sorted(member.name for member in archive.getmembers() if member.isfile())
    except (OSError, tarfile.TarError) as error:
        raise BackupError(f"Archive des photos illisible : {error}") from error
    if names != sorted(manifest["files"]):
        raise BackupError("Les photos ne correspondent pas au manifeste.")
    return manifest


def prune(target_dir, keep):
    """Keep the ``keep`` most recent backups, delete the older ones.

    Return the names deleted. A deleted personal datum leaves the backups
    with them (docs/registre-des-traitements.md).
    """
    folders = sorted(
        (p for p in Path(target_dir).iterdir() if p.is_dir() and p.name.startswith(PREFIX)),
        key=lambda p: p.name,
        reverse=True,
    )
    gone = []
    for folder in folders[keep:]:
        try:
            datetime.strptime(folder.name[len(PREFIX) :], "%Y%m%d-%H%M%S")
        except ValueError:
            continue  # not one of ours: never deleted
        shutil.rmtree(folder)
        gone.append(folder.name)
    return gone
