"""Import residents from a CSV or Excel (.xlsx) file.

Steps: read the file, analyze each row (preview), then create the
residents of the ready rows only, inside a transaction.

Libraries:
- csv (Python): https://docs.python.org/3/library/csv.html
- openpyxl, read-only mode: https://openpyxl.readthedocs.io/en/3.1/optimized.html
  defusedxml is installed: openpyxl uses it against XML attacks
  (https://openpyxl.readthedocs.io/en/stable/).
"""

import csv
import io
import unicodedata
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from accounts.phone import display_phone, normalize_phone
from housing.models import Room
from housing.services import assign_room

from .forms import free_username

MAX_SIZE = 2 * 1024 * 1024  # 2 MB: much more than a list of residents
MAX_ROWS = 500
MAX_RAW_ROWS = 5000  # rows read at most, empty ones included
MAX_UNCOMPRESSED_SIZE = 20 * 1024 * 1024  # against archives that "inflate"
UNREADABLE_XLSX = "Ce fichier Excel est illisible. Enregistrez-le de nouveau en .xlsx."
MAX_COLUMNS = 20
EXTENSIONS = (".csv", ".xlsx")

# Expected column -> accepted headers (compared without accents, spaces or case).
# The headers stay in French: users type them in their files.
HEADERS = {
    "first_name": ["prenom", "prenoms", "firstname"],
    "last_name": ["nom", "nomdefamille", "lastname"],
    # One column for both, "Awa KONÉ": split by split_name().
    "full_name": ["nomprenom", "prenomnom", "nomcomplet", "resident", "residente", "occupant"],
    "phone": ["telephone", "tel", "portable", "mobile", "telephoneportable"],
    "room": ["chambre", "nchambre", "numerodechambre", "numerochambre"],
    "arrival": ["arrivee", "datedarrivee", "datearrivee", "entree", "datedentree"],
    "email": ["email", "mail", "courriel", "adresseemail"],
}
REQUIRED = ("first_name", "last_name")
DATE_FORMATS = ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y")


class Semicolon(csv.excel):
    delimiter = ";"


class FileError(Exception):
    """The whole file is refused (format, size, headers...)."""


def _key(text):
    without_accents = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore")
    return "".join(c for c in without_accents.decode().lower() if c.isalnum())


KEY_BY_HEADER = {variant: key for key, variants in HEADERS.items() for variant in variants}


# --- Reading ---------------------------------------------------------------


def _csv_cells(content):
    """Yield the rows of a CSV. Raise FileError if the text cannot be read."""
    text = None
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise FileError(
            "Les caractères de ce fichier sont illisibles. Dans Excel, enregistrez-le "
            "en «\u00a0CSV UTF-8\u00a0»."
        )
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=";,\t")
    except csv.Error:
        dialect = Semicolon  # a single column: use the separator of French Excel
    # newline="" as the csv module docs ask.
    reader = csv.reader(io.StringIO(text, newline=""), dialect)
    try:
        for row in reader:
            yield row[:MAX_COLUMNS]
    except csv.Error as error:
        raise FileError(
            "Ce fichier CSV est mal formé (guillemets ou cellule trop longue)."
        ) from error


def _check_archive(file):
    """An .xlsx is a zip archive: refuse those that inflate too much once opened."""
    try:
        with zipfile.ZipFile(file) as archive:
            size = sum(info.file_size for info in archive.infolist())
    except (zipfile.BadZipFile, OSError) as error:
        raise FileError(UNREADABLE_XLSX) from error
    if size > MAX_UNCOMPRESSED_SIZE:
        raise FileError(UNREADABLE_XLSX)
    file.seek(0)


def _xlsx_cells(file):
    """Yield the rows of the first sheet of an .xlsx."""
    from openpyxl import load_workbook

    _check_archive(file)
    try:
        workbook = load_workbook(file, read_only=True, data_only=True)
    except Exception as error:  # trapped or damaged file: any read error refuses it
        raise FileError(UNREADABLE_XLSX) from error
    try:
        sheet = workbook.active
        # openpyxl docs: some programs write wrong dimensions.
        sheet.reset_dimensions()
        for row in sheet.iter_rows(max_col=MAX_COLUMNS, values_only=True):
            yield list(row)
    except Exception as error:
        raise FileError(UNREADABLE_XLSX) from error
    finally:
        workbook.close()  # required in read-only mode


def _strip_trailing_empty_cells(row):
    row = list(row)
    while row and str(row[-1] if row[-1] is not None else "").strip() == "":
        row.pop()
    return row


def read_file(file):
    """Return the non-empty rows of the file, header included: [(number, cells)...].

    The number is the row number in the file, empty rows included,
    so that the preview points to the right row.
    """
    name = (file.name or "").lower()
    if name.endswith(".xls"):
        raise FileError(
            "L'ancien format Excel (.xls) n'est pas pris en charge. "
            "Dans Excel : Fichier, Enregistrer sous, puis «\u00a0Classeur Excel (.xlsx)\u00a0»."
        )
    if not name.endswith(EXTENSIONS):
        raise FileError("Le fichier doit être un .csv ou un .xlsx.")
    if file.size > MAX_SIZE:
        raise FileError("Le fichier dépasse 2 Mo. Une liste de cette sorte est bien plus petite.")
    cells = _csv_cells(file.read()) if name.endswith(".csv") else _xlsx_cells(file)
    too_long = f"Le fichier dépasse {MAX_ROWS} lignes. Découpez-le en plusieurs fichiers."
    rows = []
    try:
        for number, raw in enumerate(cells, start=1):
            if number > MAX_RAW_ROWS:
                raise FileError(too_long)
            row = _strip_trailing_empty_cells(raw)
            if row:
                rows.append((number, row))
                if len(rows) > MAX_ROWS + 1:  # + 1: the header row
                    raise FileError(too_long)
    finally:
        cells.close()
    if not rows:
        raise FileError("Le fichier est vide.")
    return rows


# --- Analysis --------------------------------------------------------------


@dataclass
class ImportRow:
    number: int  # row number in the file (the header is row 1)
    first_name: str = ""
    last_name: str = ""
    phone: str = ""  # E.164 if valid, otherwise the raw input
    room: str = ""
    arrival: str = ""  # YYYY-MM-DD if valid, otherwise the raw input
    # Room without a date: arrival on the import day (not the preview day).
    auto_arrival: bool = False
    email: str = ""
    # Parsing errors (unreadable date): kept between the preview and the confirmation.
    format_errors: list = field(default_factory=list)
    format_warnings: list = field(default_factory=list)
    # Computed by _check(), at each analysis.
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    phone_valid: bool = False

    @property
    def ready(self):
        return not self.errors

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def phone_display(self):
        return display_phone(self.phone) if self.phone_valid else self.phone

    @property
    def arrival_date(self):
        if self.auto_arrival:
            return timezone.localdate()
        try:
            return date.fromisoformat(self.arrival)
        except ValueError:
            return None


def _text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def _raw_phone(value):
    text = _text(value)
    # Excel drops the leading 0 of a number typed as a number: 612345678.
    if isinstance(value, int | float) and len(text) == 9 and text[0] in "67":
        text = "0" + text
    return text


def _date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value)
    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(text, date_format).date()
        except ValueError:
            continue
    return None


def clean_name(text):
    """Without the marks some lists add (a trailing "*") nor double spaces."""
    return " ".join(text.replace("*", " ").split())


# Small words that belong to the last name: "Jean de LA FONTAINE".
PARTICLES = {
    "de",
    "du",
    "des",
    "d'",
    "van",
    "von",
    "der",
    "den",
    "da",
    "di",
    "del",
    "ben",
    "le",
    "la",
}


def _capitals(word):
    letters = [c for c in word if c.isalpha()]
    return len(letters) > 1 and all(c.isupper() for c in letters)


def split_name(text):
    """ "Mohamed ismail EL GHANNAJ" -> ("Mohamed ismail", "EL GHANNAJ", True).

    French lists write the last name in capitals, at the end ("Awa KONÉ")
    or first ("KONÉ Awa"). Small words just before it belong to it ("Jean
    de LA FONTAINE"). The third value (sure) is False when the capitals do
    not tell (all or none of the words): the preview then asks to check.
    """
    words = clean_name(text).split()
    if not words:
        return "", "", True
    caps = [_capitals(word) for word in words]
    if all(caps) or not any(caps):
        if len(words) == 1:
            return "", words[0], False
        return " ".join(words[:-1]), words[-1], False
    if caps[-1]:
        cut = len(words)
        while cut > 1 and caps[cut - 1]:
            cut -= 1
        while cut > 1 and words[cut - 1].casefold() in PARTICLES:
            cut -= 1
        return " ".join(words[:cut]), " ".join(words[cut:]), True
    if caps[0]:
        cut = 0
        while caps[cut]:
            cut += 1
        if not any(caps[cut:]):
            return " ".join(words[cut:]), " ".join(words[:cut]), True
    return " ".join(words[:-1]), words[-1], False


def has_wifi_columns(header):
    """True if the file also lists wifi accesses (username and password)."""
    from .wifi_import import KEY_BY_HEADER as WIFI_KEYS  # wifi_import imports this module

    found = {WIFI_KEYS.get(_key(title)) for title in header}
    return {"username", "password"} <= found


def _columns(header):
    columns = {}
    for index, title in enumerate(header):
        key = KEY_BY_HEADER.get(_key(title))
        if key and key not in columns:
            columns[key] = index
    # "Date" alone is the arrival, only if no column says "Arrivée".
    if "arrival" not in columns:
        dates = [i for i, title in enumerate(header) if _key(title) == "date"]
        if dates:
            columns["arrival"] = dates[0]
    if "full_name" in columns and not {"first_name", "last_name"} <= columns.keys():
        # One column with the whole name ("Nom prénom"): split by split_name().
        columns.pop("first_name", None)
        columns.pop("last_name", None)
        return columns
    titles = [_key(title) for title in header]
    first_name_title = any("prenom" in t or "firstname" in t for t in titles)
    if "first_name" not in columns and "last_name" in columns and not first_name_title:
        # "Nom" alone, no first name column: it holds the whole name.
        columns["full_name"] = columns.pop("last_name")
        return columns
    missing = [key for key in REQUIRED if key not in columns]
    if missing:
        names = " et ".join(f"«\u00a0{HEADERS[c][0].capitalize()}\u00a0»" for c in missing)
        raise FileError(
            f"La première ligne doit contenir les titres des colonnes. Il manque {names}."
        )
    return columns


def analyze(rows):
    """Analyze the rows read by read_file(). Return a list of ImportRow."""
    columns = _columns(rows[0][1])
    result = []
    for number, cells in rows[1:]:

        def value(key, cells=cells):
            index = columns.get(key)
            return cells[index] if index is not None and index < len(cells) else None

        first_name = clean_name(_text(value("first_name")))
        last_name = clean_name(_text(value("last_name")))
        guessed = False
        if "full_name" in columns:
            first_name, last_name, sure = split_name(_text(value("full_name")))
            guessed = not sure
        row = ImportRow(
            number=number,
            first_name=first_name,
            last_name=last_name,
            phone=_raw_phone(value("phone")),
            room=_text(value("room")).upper(),
            email=_text(value("email")),
        )
        raw_arrival = value("arrival")
        if _text(raw_arrival):
            day = _date(raw_arrival)
            row.arrival = day.isoformat() if day else _text(raw_arrival)
            if day is None:
                row.format_errors.append(
                    f"«\u00a0{row.arrival}\u00a0» n'est pas une date. Écrivez-la comme 01/09/2026."
                )
        elif row.room:
            row.auto_arrival = True
        if guessed:
            row.format_warnings.append(
                "Prénom et nom séparés au mieux : vérifiez-les "
                "(le nom de famille en majuscules aide)."
            )
        result.append(row)
    _check(result)
    return result


def _check(rows):
    """Compute the errors of each row: fields, duplicates in the file and in the database.

    A few queries in total, whatever the number of rows.
    """
    for row in rows:
        row.errors = list(row.format_errors)
        row.warnings = list(row.format_warnings)
        row.phone_valid = False
        if row.phone:
            try:
                row.phone = normalize_phone(row.phone)
                row.phone_valid = True
            except ValidationError as error:
                row.errors.append(f"Numéro «\u00a0{row.phone}\u00a0» : {error.messages[0]}")

    numbers = {r.phone for r in rows if r.phone_valid}
    already_taken = {u.phone: u for u in User.objects.filter(phone__in=numbers)}
    rooms = {
        room.number: room
        for room in Room.objects.filter(number__in={r.room for r in rows if r.room})
        .select_related("floor")
        .prefetch_related("stays__resident")
    }
    existing_names = {
        (first_name.casefold(), last_name.casefold())
        for first_name, last_name in User.objects.values_list("first_name", "last_name")
    }
    seen_numbers, seen_rooms = {}, {}

    for row in rows:
        if not row.first_name and not row.last_name:
            # A free room in the residence's list: nothing to create.
            row.errors = ["Pas de nom : cette ligne est ignorée."]
            row.warnings = []
            continue
        if not row.first_name:
            row.errors.append("Le prénom manque.")
        if not row.last_name:
            row.errors.append("Le nom manque.")
        if row.email:
            try:
                validate_email(row.email)
            except ValidationError:
                row.errors.append(f"«\u00a0{row.email}\u00a0» n'est pas une adresse e-mail.")

        if row.phone_valid:
            if row.phone in seen_numbers:
                row.errors.append(f"Même numéro que la ligne {seen_numbers[row.phone]}.")
            else:
                seen_numbers[row.phone] = row.number
                if row.phone in already_taken:
                    owner = already_taken[row.phone]
                    row.errors.append(
                        f"Ce numéro est déjà celui de {owner.get_full_name() or owner}."
                    )

        if row.room:
            room = rooms.get(row.room)
            if room is None:
                row.errors.append(f"La chambre {row.room} n'existe pas.")
            elif not room.active:
                row.errors.append(f"La chambre {row.room} est fermée.")
            elif row.room in seen_rooms:
                row.errors.append(f"Même chambre que la ligne {seen_rooms[row.room]}.")
            else:
                seen_rooms[row.room] = row.number
                stays = room.stays.all()
                occupant = next((s.resident for s in stays if s.is_current), None)
                day = row.arrival_date
                # A stay that ended after the wanted arrival date overlaps the new one.
                end = max(
                    (s.departure for s in stays if s.departure and day and s.departure > day),
                    default=None,
                )
                if occupant:
                    row.errors.append(
                        f"La chambre {row.room} est déjà occupée par "
                        f"{occupant.get_full_name() or occupant}."
                    )
                elif end:
                    row.errors.append(
                        f"La chambre {row.room} était occupée jusqu'au "
                        f"{end:%d/%m/%Y} : l'arrivée doit être à partir de cette date."
                    )

        if (row.first_name.casefold(), row.last_name.casefold()) in existing_names:
            row.warnings.append(
                "Une fiche existe déjà à ce nom. Vérifiez que ce n'est pas la même personne."
            )


# --- Storage between the preview and the confirmation ----------------------


def to_session(rows):
    return [asdict(row) for row in rows]


def from_session(data):
    """Rebuild the rows and check them again: the database may have changed."""
    rows = [ImportRow(**d) for d in data]
    _check(rows)
    return rows


# --- Import ----------------------------------------------------------------


@transaction.atomic
def run_import(rows):
    """Create one resident (and one stay) per ready row. All or nothing.

    Return the list of created residents. Raise ValidationError if a row is
    refused at the last moment; nothing is saved then.
    """
    rooms = {room.number: room for room in Room.objects.filter(number__in=[r.room for r in rows])}
    created = []
    for row in rows:
        if not row.ready:
            continue
        try:
            created.append(_create(row, rooms))
        except ValidationError as error:
            raise ValidationError(f"Ligne {row.number} : {' '.join(error.messages)}") from error
    return created


def _create(row, rooms):
    resident = User(
        username=free_username(row.first_name, row.last_name),
        first_name=row.first_name,
        last_name=row.last_name,
        phone=row.phone,
        email=row.email,
    )
    resident.set_unusable_password()
    resident.full_clean(exclude=["password"])
    resident.save()
    if row.room:
        assign_room(resident, rooms[row.room], row.arrival_date)
    return resident
