"""First loading of a new server from a YAML file (card T38).

    python manage.py load_initial_data deploy/initial-data.yaml --dry-run
    python manage.py load_initial_data deploy/initial-data.yaml

The file (example: deploy/initial-data.example.yaml) lists the settings of
the residence, its floors and rooms, and the first staff accounts. The
whole file is checked first; then everything is created in one
transaction, or nothing. Only what is missing is created: run again, the
command changes nothing, so a floor added later in the admin site stays
as it is. Residents come with the Excel import (card T08).

YAML is read with yaml.safe_load (never yaml.load): the file can only
hold plain data. https://pyyaml.org/wiki/PyYAMLDocumentation
"""

from dataclasses import dataclass, field

import yaml
from django.core.exceptions import ValidationError
from django.db import transaction

from accounts.phone import normalize_phone
from accounts.roles import STAFF_ROLES

SETTINGS_FIELDS = (
    "organization_name",
    "organization_address",
    "privacy_contact",
    "emergency_phone",
)
ROLE_NAMES = {role.value: role for role in STAFF_ROLES}


class DataError(Exception):
    """The file is wrong: nothing was loaded."""


@dataclass
class Plan:
    """What the file asks for, checked, ready to be applied."""

    settings: dict = field(default_factory=dict)
    floors: list = field(default_factory=list)  # (number, name, visit_order, [rooms])
    staff: list = field(default_factory=list)  # dicts


@dataclass
class Report:
    created: list = field(default_factory=list)
    kept: list = field(default_factory=list)


def read(path):
    try:
        with open(path, encoding="utf-8") as source:
            data = yaml.safe_load(source)
    except OSError as error:
        raise DataError(f"Fichier illisible : {error}") from error
    except yaml.YAMLError as error:
        raise DataError(f"YAML invalide : {error}") from error
    if not isinstance(data, dict):
        raise DataError("Le fichier doit contenir les rubriques residence, floors et staff.")
    return check(data)


def _rooms(items, floor):
    if items is None:
        return []
    if not isinstance(items, list):
        raise DataError(f'Étage {floor} : rooms est une liste, par exemple ["101-120"].')
    rooms = []
    for item in items:
        # Quotes required: unquoted, YAML reads 010 as the number 8.
        if not isinstance(item, str):
            raise DataError(
                f'Étage {floor} : écrivez chaque chambre entre guillemets, par exemple "{item}".'
            )
        text = item.strip()
        if "-" in text:
            start, _, end = text.partition("-")
            if not (start.isdigit() and end.isdigit()) or int(start) > int(end):
                raise DataError(f"Étage {floor} : plage de chambres invalide «\u00a0{text}\u00a0».")
            width = len(start)
            rooms += [str(n).zfill(width) for n in range(int(start), int(end) + 1)]
        elif text:
            rooms.append(text)
    for number in rooms:
        if len(number) > 10:
            raise DataError(f"Chambre «\u00a0{number}\u00a0» : 10 caractères au plus.")
    return rooms


def check(data):
    """Check the whole file before touching the database."""
    unknown = set(data) - {"residence", "floors", "staff"}
    if unknown:
        raise DataError(f"Rubrique inconnue : {', '.join(sorted(unknown))}.")
    for key, kind in (("residence", dict), ("floors", list), ("staff", list)):
        if data.get(key) is not None and not isinstance(data[key], kind):
            shape = "des réglages (nom : valeur)" if kind is dict else "une liste (lignes en tiret)"
            raise DataError(f"{key} : il faut {shape}.")
    plan = Plan()

    for key, value in (data.get("residence") or {}).items():
        if key not in SETTINGS_FIELDS:
            raise DataError(f"residence : réglage inconnu «\u00a0{key}\u00a0».")
        plan.settings[key] = "" if value is None else str(value).strip()

    seen_rooms = set()
    for entry in data.get("floors") or []:
        if not isinstance(entry, dict) or "number" not in entry:
            raise DataError("floors : chaque étage a un numéro (number).")
        number = entry["number"]
        if isinstance(number, bool) or not isinstance(number, int) or not 0 <= number <= 99:
            raise DataError(
                f"Étage «\u00a0{number}\u00a0» : un nombre entier, 0 pour le rez-de-chaussée."
            )
        rooms = _rooms(entry.get("rooms"), number)
        for room in rooms:
            if room in seen_rooms:
                raise DataError(f"Chambre «\u00a0{room}\u00a0» : en double dans le fichier.")
            seen_rooms.add(room)
        order = entry.get("visit_order", number)
        if isinstance(order, bool) or not isinstance(order, int) or not 0 <= order <= 999:
            raise DataError(f"Étage {number} : visit_order est un nombre entier positif.")
        name = entry.get("name") or ""
        if not isinstance(name, str) or len(name) > 60:
            raise DataError(f"Étage {number} : name est un texte de 60 caractères au plus.")
        plan.floors.append((number, name.strip(), order, rooms))

    usernames = set()
    for entry in data.get("staff") or []:
        if not isinstance(entry, dict) or not entry.get("username"):
            raise DataError("staff : chaque compte a un identifiant (username).")
        username = str(entry["username"]).strip()
        if len(username) > 150 or not all(c.isalnum() or c in "@.+-_" for c in username):
            raise DataError(
                f"Compte «\u00a0{username}\u00a0» : lettres, chiffres et @ . + - _ seulement."
            )
        for key in ("first_name", "last_name", "email"):
            if entry.get(key) is not None and not isinstance(entry[key], str):
                raise DataError(f"Compte «\u00a0{username}\u00a0» : {key} est un texte.")
        if username in usernames:
            raise DataError(f"Compte «\u00a0{username}\u00a0» : en double dans le fichier.")
        usernames.add(username)
        roles = entry.get("roles") or []
        if not isinstance(roles, list):
            roles = [roles]
        wrong = [r for r in roles if not isinstance(r, str) or r not in ROLE_NAMES]
        if not roles or wrong:
            raise DataError(
                f"Compte «\u00a0{username}\u00a0» : rôles parmi {', '.join(sorted(ROLE_NAMES))}."
            )
        try:
            phone = normalize_phone(str(entry.get("phone") or ""))
        except ValidationError as error:
            raise DataError(f"Compte «\u00a0{username}\u00a0» : {error.messages[0]}") from None
        plan.staff.append(
            {
                "username": username,
                "first_name": str(entry.get("first_name") or ""),
                "last_name": str(entry.get("last_name") or ""),
                "email": str(entry.get("email") or ""),
                "phone": phone,
                "roles": {ROLE_NAMES[r] for r in roles},
            }
        )
    return plan


def apply(plan, dry_run=False):
    """Create what is missing. With ``dry_run``, everything is undone at the
    end: the report says what would be created."""
    from accounts.models import User
    from accounts.roles import set_roles
    from housing.models import Floor, Room
    from residence.models import ResidenceSettings

    report = Report()
    with transaction.atomic():
        row = ResidenceSettings.load()
        defaults = ResidenceSettings()
        changed = []
        for key, value in plan.settings.items():
            # Only a value still at its default: a setting changed on the
            # page "Réglages" wins over the file.
            if getattr(row, key) == getattr(defaults, key) and value != getattr(row, key):
                setattr(row, key, value)
                changed.append(key)
            else:
                report.kept.append(f"réglage {key}")
        if changed:
            row.full_clean()
            row.save()
            report.created += [f"réglage {key}" for key in changed]

        for number, name, order, rooms in plan.floors:
            floor, made = Floor.objects.get_or_create(
                number=number, defaults={"name": name, "visit_order": order}
            )
            (report.created if made else report.kept).append(f"étage {number}")
            for room_number in rooms:
                room, made = Room.objects.get_or_create(
                    number=room_number, defaults={"floor": floor}
                )
                if not made and room.floor_id != floor.pk:
                    raise DataError(
                        f"Chambre «\u00a0{room_number}\u00a0» : "
                        f"déjà sur l'étage {room.floor.number}."
                    )
                (report.created if made else report.kept).append(f"chambre {room_number}")

        for person in plan.staff:
            user = User.objects.filter(username=person["username"]).first()
            if user:
                report.kept.append(f"compte {person['username']}")
                continue
            user = User(
                username=person["username"],
                first_name=person["first_name"],
                last_name=person["last_name"],
                email=person["email"],
                phone=person["phone"],
            )
            user.set_unusable_password()  # passkeys only (card T13)
            user.full_clean()
            user.save()
            set_roles(user, person["roles"])
            report.created.append(f"compte {person['username']}")

        if dry_run:
            transaction.set_rollback(True)
    return report
