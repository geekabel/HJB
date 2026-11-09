"""Backups of the database and of the report photos (card T37).

A backup is a folder named after its time, for example
``hjb-20261107-0300``, with:

- the database:
  - PostgreSQL (production, card T38): ``db.dump``, made by pg_dump in its
    custom format, from one consistent snapshot;
  - SQLite (development): ``db.sqlite3``, a copy made by SQLite's backup
    API (https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup);
- ``media.tar.gz``: the photo files (MEDIA_ROOT);
- ``manifest.json``: what the database holds (tables or rows per table),
  the photos, and a SHA-256 of both archives.

``verify`` reads the backup back and checks it against the manifest: a
backup is only a backup once it has been read back. With PostgreSQL,
``verify(restore=True)`` also restores it into a throwaway database.

What a backup does not hold, on purpose (card T37 review):
- the keys (SECRET_KEY, wifi keys, VAPID): they stay in the server's
  environment and are kept apart, so a stolen backup cannot open the wifi
  passwords;
- the sessions: a stolen backup must not log anyone in;
- the secrets of the staff app codes (TOTP): with them, anyone could
  compute the codes. After a restore, the staff link their app again.
For SQLite the copy is then vacuumed: deleted rows leave no trace in free
pages. pg_dump never writes their data at all.
"""

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.utils import timezone

PREFIX = "hjb-"
DB_NAME = "db.sqlite3"
PG_NAME = "db.dump"
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
    if connection.vendor not in ("sqlite", "postgresql"):
        raise BackupError(f"Base non prise en charge : {connection.vendor}.")
    now = timezone.localtime(now)
    folder = Path(target_dir) / f"{PREFIX}{now:%Y%m%d-%H%M%S}"
    folder.mkdir(parents=True, exist_ok=False)
    folder.chmod(0o700)  # personal data: the owner only

    if connection.vendor == "postgresql":
        database = _dump_postgres(folder)
    else:
        database = _copy_sqlite(folder)

    media_root = Path(settings.MEDIA_ROOT)
    files = []
    with tarfile.open(folder / MEDIA_NAME, "w:gz") as archive:
        if media_root.is_dir():
            for path in sorted(p for p in media_root.rglob("*") if p.is_file()):
                name = path.relative_to(media_root).as_posix()
                archive.add(path, arcname=name)
                files.append(name)

    db_file = database.pop("file")
    manifest = {
        "made_at": now.isoformat(),
        # Which database was copied: a cron line without the production
        # settings would back up the development one.
        "database": str(connection.settings_dict["NAME"]),
        "format": connection.vendor,
        "db_file": db_file,
        "left_out": list(LEFT_OUT),
        **database,
        "files": files,
        "sha256": {name: _sha256(folder / name) for name in (db_file, MEDIA_NAME)},
    }
    (folder / MANIFEST).write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    for path in folder.iterdir():
        path.chmod(0o600)
    return folder


def _copy_sqlite(folder):
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
    return {"file": DB_NAME, "rows": counts}


def _pg_environment(name=None):
    """libpq variables for pg_dump and pg_restore, from DATABASES.
    https://www.postgresql.org/docs/current/libpq-envars.html"""
    found = connection.settings_dict
    variables = {
        "PGDATABASE": name or found["NAME"],
        "PGUSER": found.get("USER", ""),
        "PGPASSWORD": found.get("PASSWORD", ""),
        "PGHOST": found.get("HOST", ""),
        "PGPORT": str(found.get("PORT", "") or ""),
    }
    return {**os.environ, **{key: value for key, value in variables.items() if value}}


def _run(command, name=None):
    try:
        return subprocess.run(
            command, env=_pg_environment(name), capture_output=True, text=True, check=True
        )
    except FileNotFoundError as error:
        raise BackupError(f"{command[0]} est introuvable : installez postgresql-client.") from error
    except subprocess.CalledProcessError as error:
        raise BackupError(f"{command[0]} a échoué : {error.stderr.strip()[:300]}") from error


def _dump_postgres(folder):
    """pg_dump in its custom format, one consistent snapshot of the base.
    The data of LEFT_OUT stays out (their tables are in it, empty).
    https://www.postgresql.org/docs/current/app-pgdump.html"""
    command = ["pg_dump", "--format=custom", "--no-owner", f"--file={folder / PG_NAME}"]
    command += [f"--exclude-table-data={table}" for table in LEFT_OUT]
    _run(command)
    return {"file": PG_NAME, "tables": _pg_tables(folder / PG_NAME)}


def _pg_tables(path):
    """The tables whose data is in the dump, read from its table of contents."""
    listing = _run(["pg_restore", "--list", str(path)]).stdout
    found = []
    for line in listing.splitlines():
        parts = line.split()
        if "TABLE" in parts and "DATA" in parts:
            index = parts.index("DATA")
            if len(parts) > index + 2:
                found.append(parts[index + 2])
    return sorted(found)


def verify(folder, restore=False):
    """Read a backup back. Return its manifest; raise BackupError if wrong.

    With ``restore`` (PostgreSQL), the dump is also restored into a
    throwaway database, counted, then dropped: the real proof.
    """
    folder = Path(folder)
    try:
        manifest = json.loads((folder / MANIFEST).read_text())
    except (OSError, ValueError) as error:
        raise BackupError(f"Manifeste illisible : {error}") from error
    for name, expected in manifest["sha256"].items():
        if not (folder / name).is_file() or _sha256(folder / name) != expected:
            raise BackupError(f"{name} : fichier absent ou modifié.")
    if manifest.get("format", "sqlite") == "postgresql":
        if _pg_tables(folder / manifest["db_file"]) != manifest["tables"]:
            raise BackupError("Les tables ne correspondent pas au manifeste.")
        if restore:
            manifest["restored_users"] = _restore_check(folder / manifest["db_file"])
    else:
        _verify_sqlite(folder / manifest.get("db_file", DB_NAME), manifest)
    try:
        with tarfile.open(folder / MEDIA_NAME, "r:gz") as archive:
            names = sorted(member.name for member in archive.getmembers() if member.isfile())
    except (OSError, tarfile.TarError) as error:
        raise BackupError(f"Archive des photos illisible : {error}") from error
    if names != sorted(manifest["files"]):
        raise BackupError("Les photos ne correspondent pas au manifeste.")
    return manifest


def _verify_sqlite(path, manifest):
    database = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
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


def _restore_check(path):
    """Restore into "<base>_restore_check", count the accounts, drop it.
    The database role needs CREATEDB (deploy/deploy.sh gives it)."""
    scratch = f"{connection.settings_dict['NAME']}_restore_check"
    _run(["dropdb", "--if-exists", scratch])
    _run(["createdb", scratch])
    try:
        _run(["pg_restore", "--no-owner", "--exit-on-error", f"--dbname={scratch}", str(path)])
        output = _run(["psql", "-At", "-c", "SELECT COUNT(*) FROM accounts_user"], scratch)
        return int(output.stdout.strip() or 0)
    finally:
        _run(["dropdb", "--if-exists", scratch])


def describe(manifest):
    """ "568 lignes, 3 photos" (SQLite) or "41 tables, 3 photos" (PostgreSQL)."""
    photos = f"{len(manifest['files'])} photos"
    if "rows" in manifest:
        return f"{sum(manifest['rows'].values())} lignes, {photos}"
    return f"{len(manifest.get('tables', []))} tables, {photos}"


def prune(target_dir, keep):
    """Keep the ``keep`` most recent backups, delete the older ones.

    Return the names deleted. A deleted personal datum leaves the backups
    with them (register of processing activities, kept outside the repository).
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
