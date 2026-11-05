"""Phone numbers: free input, stored in the international E.164 format.

Library: phonenumbers (https://github.com/daviddrysdale/python-phonenumbers).
A mobile number is required, because it is used to send SMS.
"""

import phonenumbers
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator

DEFAULT_REGION = "FR"

MOBILE_TYPES = {
    phonenumbers.PhoneNumberType.MOBILE,
    phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE,
}

# Form stored in the database: "+", country code, then 15 digits at most.
validate_e164 = RegexValidator(
    regex=r"^\+[1-9]\d{6,14}$",
    message="Le numéro doit être au format international, par exemple +33612345678.",
    code="phone_e164",
)


def normalize_phone(text, region=DEFAULT_REGION):
    """Turn an input ("06 12 34 56 78") into E.164 ("+33612345678").

    Return an empty string if nothing is entered. Raise ValidationError if the
    number cannot be read, does not exist or is not a mobile number.
    """
    text = (text or "").strip()
    if not text:
        return ""
    try:
        number = phonenumbers.parse(text, region)
    except phonenumbers.NumberParseException as error:
        raise ValidationError(
            "Ce numéro est illisible. Écrivez-le comme 06 12 34 56 78 ou +33 6 12 34 56 78.",
            code="phone_unreadable",
        ) from error
    if not phonenumbers.is_valid_number(number):
        raise ValidationError(
            "Ce numéro n'existe pas. Vérifiez les chiffres.", code="phone_invalid"
        )
    if phonenumbers.number_type(number) not in MOBILE_TYPES:
        raise ValidationError(
            "Il faut un numéro de portable, pour pouvoir recevoir les SMS.",
            code="phone_not_mobile",
        )
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def display_phone(e164, region=DEFAULT_REGION):
    """Readable form: "06 12 34 56 78" for France, international otherwise."""
    if not e164:
        return ""
    number = phonenumbers.parse(e164, None)
    if phonenumbers.region_code_for_number(number) == region:
        return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.NATIONAL)
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.INTERNATIONAL)


def mask_phone(e164, region=DEFAULT_REGION):
    """Hide the middle digits: "06 •• •• •• 78".

    We keep the first group (country code or 06/07) and the last two
    digits: enough to recognize a number, not enough to call it.
    """
    try:
        text = display_phone(e164, region)
    except phonenumbers.NumberParseException:
        text = e164  # unreadable number: we still mask its digits
    if not text:
        return ""
    start = text.find(" ")
    if start == -1:
        start = 2
    positions = [i for i, c in enumerate(text) if c.isdigit() and i > start]
    to_hide = set(positions[:-2])
    return "".join("•" if i in to_hide else c for i, c in enumerate(text))
