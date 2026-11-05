"""Import the existing list of wifi accesses from a CSV or Excel file (card T15b).

The residence already keeps a list: username -> room -> person. This module
reads it, checks each row (preview), then records the ready rows with
housing.wifi.set_access(), all or nothing.

The file is read with the same functions as the resident import (size, rows,
encodings, .xlsx checks). Between the preview and the confirmation, the
passwords stay encrypted in the session, never in clear.
"""

from dataclasses import asdict, dataclass, field
from datetime import date

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from housing import wifi, wifi_crypto
from housing.models import Room, Stay, WifiAccess

from .bulk_import import FileError, _date, _key, _text

# Expected column -> accepted headers (compared without accents, spaces or case).
# The headers stay in French: users type them in their files.
HEADERS = {
    "username": ["identifiant", "login", "utilisateur", "nomdutilisateur", "username"],
    "password": ["motdepasse", "mdp", "pass", "password", "code"],
    "room": ["chambre", "nchambre", "numerodechambre", "numerochambre"],
    "resident": ["resident", "residente", "nom", "personne", "occupant", "nomprenom"],
    "expires_on": [
        "valablejusquau",
        "expiration",
        "dateexpiration",
        "datedexpiration",
        "fin",
        "datedefin",
    ],
}
REQUIRED = ("username", "password", "room")
KEY_BY_HEADER = {variant: key for key, variants in HEADERS.items() for variant in variants}
# Column titles of the template file.
TEMPLATE_HEADERS = ["Identifiant", "Mot de passe", "Chambre", "Résident", "Valable jusqu'au"]


@dataclass
class WifiRow:
    number: int  # row number in the file (the header is row 1)
    username: str = ""
    encrypted_password: str = ""  # never in clear outside read/record
    room: str = ""
    resident: str = ""  # name written in the file, only to compare
    expires_on: str = ""  # YYYY-MM-DD if valid, otherwise the raw input
    auto_expiry: bool = False  # no date in the file: one year from the import day
    # Errors found while reading the file: kept until the confirmation.
    format_errors: list = field(default_factory=list)
    format_warnings: list = field(default_factory=list)
    # Computed by _check(), at each analysis.
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    occupant: str = ""
    stay_pk: int | None = None
    replaces_pk: int | None = None

    @property
    def ready(self):
        return not self.errors

    @property
    def expiry_date(self):
        if self.auto_expiry:
            return wifi.default_expiry()
        try:
            return date.fromisoformat(self.expires_on)
        except ValueError:
            return None

    @property
    def state(self):
        """What the confirmation relies on: it must not change after the preview."""
        return f"{self.number}:{self.stay_pk or 0}:{self.replaces_pk or 0}"


def _columns(header):
    columns = {}
    for index, title in enumerate(header):
        key = KEY_BY_HEADER.get(_key(title))
        if key and key not in columns:
            columns[key] = index
    missing = [key for key in REQUIRED if key not in columns]
    if missing:
        names = " et ".join(f"« {TEMPLATE_HEADERS[list(HEADERS).index(c)]} »" for c in missing)
        raise FileError(
            f"La première ligne doit contenir les titres des colonnes. Il manque {names}."
        )
    return columns


NUMBER_CELL = "Excel a lu « {value} » comme un nombre. Vérifiez qu'il n'a pas retiré un 0 au début."


@sensitive_variables("password")
def analyze(rows):
    """Analyze the rows read by bulk_import.read_file(). Return a list of WifiRow.

    Raises ImproperlyConfigured if the wifi encryption keys are missing.
    """
    columns = _columns(rows[0][1])
    result = []
    for number, cells in rows[1:]:

        def value(key, cells=cells):
            index = columns.get(key)
            return cells[index] if index is not None and index < len(cells) else None

        row = WifiRow(
            number=number,
            username=_text(value("username")),
            room=_text(value("room")).upper(),
            resident=_text(value("resident")),
        )
        password = _text(value("password"))
        if password:
            row.encrypted_password = wifi_crypto.encrypt(password)
        for key in ("username", "password"):
            raw = value(key)
            if isinstance(raw, int | float) and not isinstance(raw, bool):
                row.format_warnings.append(NUMBER_CELL.format(value=_text(raw)))
        for label, text in (("L'identifiant", row.username), ("Le mot de passe", password)):
            if not text:
                row.format_errors.append(f"{label} manque.")
            elif error := wifi.check_credential(text):
                row.format_errors.append(f"{label} : {error}")
        raw_expiry = value("expires_on")
        if _text(raw_expiry):
            day = _date(raw_expiry)
            row.expires_on = day.isoformat() if day else _text(raw_expiry)
            if day is None:
                row.format_errors.append(
                    f"« {row.expires_on} » n'est pas une date. Écrivez-la comme 01/09/2027."
                )
        else:
            row.auto_expiry = True
        result.append(row)
    _check(result)
    return result


def _same_person(written, occupant):
    """True if every word written in the file is in the occupant's name."""
    occupant_words = {_key(word) for word in occupant.split()}
    return {_key(word) for word in written.split()} <= occupant_words


def _check(rows):
    """Compute the errors of each row: fields, duplicates in the file and in the database.

    A few queries in total, whatever the number of rows.
    """
    rooms = {
        room.number: room
        for room in Room.objects.filter(number__in={r.room for r in rows if r.room})
    }
    stays = {
        stay.room_id: stay
        for stay in Stay.objects.current()
        .filter(room__in=rooms.values())
        .select_related("resident")
    }
    active = {
        access.room_id: access
        for access in WifiAccess.objects.filter(room__in=rooms.values(), active=True)
    }
    # Usernames already used by an active access, and the room of each.
    taken = dict(
        WifiAccess.objects.filter(
            active=True, username__in={r.username for r in rows if r.username}
        ).values_list("username", "room__number")
    )
    today = timezone.localdate()
    seen_usernames, seen_rooms = {}, {}

    for row in rows:
        row.errors = list(row.format_errors)
        row.warnings = list(row.format_warnings)
        row.occupant = ""
        row.stay_pk = row.replaces_pk = None

        if row.username:
            if row.username in seen_usernames:
                row.errors.append(f"Même identifiant que la ligne {seen_usernames[row.username]}.")
            else:
                seen_usernames[row.username] = row.number
                if taken.get(row.username, row.room) != row.room:
                    row.errors.append(
                        f"Cet identifiant sert déjà à la chambre {taken[row.username]}."
                    )

        day = row.expiry_date
        if day is not None and day <= today:
            row.errors.append("La date de fin doit être dans le futur.")

        if not row.room:
            row.errors.append("La chambre manque.")
            continue
        room = rooms.get(row.room)
        if room is None:
            row.errors.append(f"La chambre {row.room} n'existe pas.")
            continue
        if row.room in seen_rooms:
            row.errors.append(f"Même chambre que la ligne {seen_rooms[row.room]}.")
            continue
        seen_rooms[row.room] = row.number
        stay = stays.get(room.pk)
        if stay is None:
            row.errors.append(
                f"La chambre {row.room} n'a pas de résident en ce moment. "
                "Importez ou créez d'abord sa fiche."
            )
            continue
        row.stay_pk = stay.pk
        row.occupant = stay.resident.get_full_name() or str(stay.resident)
        if row.resident and not _same_person(row.resident, row.occupant):
            row.warnings.append(
                f"Le fichier indique « {row.resident} ». Vérifiez que c'est bien la bonne chambre."
            )
        current = active.get(room.pk)
        if current:
            row.replaces_pk = current.pk
            row.warnings.append(f"Remplace l'accès actuel ({current.username}).")


# --- Storage between the preview and the confirmation ----------------------


def to_session(rows):
    return [asdict(row) for row in rows]


def from_session(data):
    """Rebuild the rows and check them again: the database may have changed."""
    rows = [WifiRow(**d) for d in data]
    _check(rows)
    return rows


# --- Import ----------------------------------------------------------------


@sensitive_variables("password")
@transaction.atomic
def run_import(rows, *, by, request=None):
    """Record the access of each ready row. All or nothing.

    Return the number of accesses recorded. Raise ValidationError if a row is
    refused at the last moment (a departure, another recording); nothing is
    saved then.
    """
    stays = {
        stay.pk: stay
        for stay in Stay.objects.filter(pk__in=[r.stay_pk for r in rows if r.ready]).select_related(
            "room"
        )
    }
    replaced = {
        access.pk: access
        for access in WifiAccess.objects.filter(pk__in=[r.replaces_pk for r in rows if r.ready])
    }
    count = 0
    for row in rows:
        if not row.ready:
            continue
        stay = stays.get(row.stay_pk)
        if stay is None:
            raise ValidationError(f"Ligne {row.number} : le séjour n'existe plus.")
        password = wifi_crypto.decrypt(row.encrypted_password)
        try:
            wifi.set_access(
                stay.room,
                username=row.username,
                password=password,
                expires_on=row.expiry_date,
                stay=stay,
                replaces=replaced.get(row.replaces_pk),
                by=by,
                request=request,
            )
        except ValidationError as error:
            raise ValidationError(f"Ligne {row.number} : {' '.join(error.messages)}") from error
        count += 1
    return count
