"""Import the existing list of wifi accesses from a CSV or Excel file (card T15b).

The residence already keeps a list: username -> room -> person. This module
reads it, checks each row (preview), then records the ready rows with
housing.wifi.set_access(), all or nothing.

The file is read with the same functions as the resident import (size, rows,
encodings, .xlsx checks). Between the preview and the confirmation, the
passwords stay encrypted in the session, never in clear.
"""

import re
from dataclasses import asdict, dataclass, field
from datetime import date

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from housing import wifi, wifi_crypto
from housing.models import Room, Stay, WifiAccess, WifiSettings

from .bulk_import import FileError, _date, _key, _text

# Expected column -> accepted headers (compared without accents, spaces or case).
# The headers stay in French: users type them in their files.
HEADERS = {
    # No "code" nor "utilisateur": a door code or a person's name would be taken silently.
    "username": ["identifiant", "login", "nomdutilisateur", "username"],
    "password": ["motdepasse", "mdp", "pass", "password"],
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
    unchanged: bool = False  # same username and password as the current access

    @property
    def ready(self):
        return not self.errors and not self.unchanged

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


def _label(key):
    return TEMPLATE_HEADERS[list(HEADERS).index(key)]


def _columns(header):
    columns = {}
    for index, title in enumerate(header):
        key = KEY_BY_HEADER.get(_key(title))
        if key is None:
            continue
        if key in columns:
            raise FileError(
                f"Deux colonnes peuvent être «\u00a0{_label(key)}\u00a0» : "
                f"«\u00a0{header[columns[key]]}\u00a0» "
                f"et «\u00a0{title}\u00a0». Gardez-en une seule."
            )
        columns[key] = index
    missing = [f"«\u00a0{_label(key)}\u00a0»" for key in REQUIRED if key not in columns]
    if missing:
        names = missing[0] if len(missing) == 1 else f"{', '.join(missing[:-1])} et {missing[-1]}"
        raise FileError(
            f"La première ligne doit contenir les titres des colonnes. Il manque {names}."
        )
    return columns


# A value that Excel turned into a number in scientific notation ("2,34E+58").
SCIENTIFIC = re.compile(r"^\d+([.,]\d+)?E[+-]?\d+$", re.IGNORECASE)
MANGLED = (
    "{label} a été transformé en nombre par Excel. Mettez la colonne au format Texte, "
    "puis recopiez les valeurs."
)
# The password value never goes into a message: messages are shown and kept in the session.
NUMBER_CELL = "{label} a été lu comme un nombre. Vérifiez qu'Excel n'a pas retiré un 0 au début."


def _credential_problems(label, raw, text, settings_row):
    """Return (errors, warnings) for a username or password cell. Never quote the value."""
    if not text:
        return [f"{label} manque."], []
    is_number = isinstance(raw, int | float) and not isinstance(raw, bool)
    # Excel keeps 15 digits: a larger or decimal number is no longer the typed value.
    if isinstance(raw, float) and (not raw.is_integer() or abs(raw) >= 1e15):
        return [MANGLED.format(label=label)], []
    if SCIENTIFIC.match(text):
        return [MANGLED.format(label=label)], []
    if error := wifi.check_credential(text):
        return [f"{label} : {error[0].lower()}{error[1:]}"], []
    warnings = [NUMBER_CELL.format(label=label)] if is_number else []
    length = (
        settings_row.username_length if label == "L'identifiant" else settings_row.password_length
    )
    if len(text) != length or not set(text) <= set(settings_row.alphabet):
        warnings.append(
            f"{label} ne suit pas le format du portail ({length} caractères). Vérifiez-le."
        )
    return [], warnings


@sensitive_variables()
def analyze(rows):
    """Analyze the rows read by bulk_import.read_file(). Return a list of WifiRow.

    Raises ImproperlyConfigured if the wifi encryption keys are missing.
    """
    columns = _columns(rows[0][1])
    settings_row = WifiSettings.load()
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
        for label, raw, text in (
            ("L'identifiant", value("username"), row.username),
            ("Le mot de passe", value("password"), password),
        ):
            errors, warnings = _credential_problems(label, raw, text, settings_row)
            row.format_errors += errors
            row.format_warnings += warnings
        raw_expiry = value("expires_on")
        if _text(raw_expiry):
            day = _date(raw_expiry)
            row.expires_on = day.isoformat() if day else _text(raw_expiry)
            if day is None:
                row.format_errors.append(
                    f"«\u00a0{row.expires_on}\u00a0» n'est pas une date. "
                    "Écrivez-la comme 01/09/2027."
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
        row.unchanged = False

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
                f"Le fichier indique «\u00a0{row.resident}\u00a0». "
                "Vérifiez que c'est bien la bonne chambre."
            )
        current = active.get(room.pk)
        if current:
            row.replaces_pk = current.pk
            if not row.errors and _same_access(row, current):
                # Sending the same list again changes nothing (history, expiry).
                row.unchanged = True
                row.warnings = []
            else:
                row.warnings.append(f"Remplace l'accès actuel ({current.username}).")


@sensitive_variables()
def _same_access(row, access):
    if row.username != access.username:
        return False
    try:
        return wifi_crypto.decrypt(row.encrypted_password) == wifi_crypto.decrypt(
            access.encrypted_password
        )
    except wifi_crypto.WifiDecryptionError:
        return False


# --- Storage between the preview and the confirmation ----------------------


def to_session(rows):
    return [asdict(row) for row in rows]


def from_session(data):
    """Rebuild the rows and check them again: the database may have changed."""
    rows = [WifiRow(**d) for d in data]
    _check(rows)
    return rows


# --- Import ----------------------------------------------------------------


@sensitive_variables()
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
            raise ValidationError(
                f"Ligne {row.number} : {' '.join(error.messages)}",
                code=getattr(error, "code", None),
            ) from error
        count += 1
    return count
