"""The {fields} of a message, filled in for each recipient (card T20).

    Bonjour {prénom}, visite de la chambre {chambre} le {date} entre {début} et {fin}.

Field names stay in French: the staff type them in the texts.
"""

import re

from django.utils.formats import date_format

FIELD = re.compile(r"\{([^{}\s]{1,20})\}")
FIELDS = {
    "prénom": "Prénom du résident",
    "chambre": "Numéro de sa chambre",
    "date": "Date indiquée dans le message",
    "début": "Heure de début",
    "fin": "Heure de fin",
}


def fields_in(text):
    return list(dict.fromkeys(FIELD.findall(text or "")))


def check_text(text):
    """French error messages for unknown fields (empty list if all is fine)."""
    unknown = [name for name in fields_in(text) if name not in FIELDS]
    if not unknown:
        return []
    names = ", ".join(f"{{{name}}}" for name in unknown)
    known = ", ".join(f"{{{name}}}" for name in FIELDS)
    s = "s" if len(unknown) > 1 else ""
    return [f"Champ{s} inconnu{s} : {names}. Champs possibles : {known}."]


def format_time(value):
    """15:00 -> "15 h", 15:30 -> "15 h 30" (French typography)."""
    return f"{value.hour} h" if value.minute == 0 else f"{value.hour} h {value.minute:02d}"


def values_for(campaign, resident=None, room=None):
    return {
        "prénom": (resident.first_name or resident.get_username()) if resident else "",
        "chambre": room.number if room else "",
        "date": date_format(campaign.event_date, "l j F") if campaign.event_date else "",
        "début": format_time(campaign.start_time) if campaign.start_time else "",
        "fin": format_time(campaign.end_time) if campaign.end_time else "",
    }


def fill(text, values):
    """Replace each known field; an unknown one stays as written."""
    return FIELD.sub(lambda m: values.get(m.group(1), m.group(0)), text or "")


def uses_event_fields(campaign):
    """Whether the texts use {date}, {début} or {fin}: their fields stay shown."""
    used = set().union(*(fields_in(t) for t in (campaign.title, campaign.body, campaign.sms_body)))
    return bool(used & {"date", "début", "fin"})


def missing_values(campaign):
    """Fields used in the texts whose value is not given (date, start, end)."""
    used = set().union(*(fields_in(t) for t in (campaign.title, campaign.body, campaign.sms_body)))
    missing = []
    for name, value in (
        ("date", campaign.event_date),
        ("début", campaign.start_time),
        ("fin", campaign.end_time),
    ):
        if name in used and value is None:
            missing.append(name)
    return missing
