"""Numéros de téléphone : saisie libre, stockage au format international E.164.

Bibliothèque : phonenumbers (https://github.com/daviddrysdale/python-phonenumbers).
On exige un numéro de portable, car il sert à envoyer des SMS.
"""

import phonenumbers
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator

REGION_PAR_DEFAUT = "FR"

TYPES_PORTABLES = {
    phonenumbers.PhoneNumberType.MOBILE,
    phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE,
}

# Forme stockée en base : « + », indicatif pays, puis 15 chiffres au plus.
valider_e164 = RegexValidator(
    regex=r"^\+[1-9]\d{6,14}$",
    message="Le numéro doit être au format international, par exemple +33612345678.",
    code="telephone_e164",
)


def normaliser_telephone(texte, region=REGION_PAR_DEFAUT):
    """Transforme une saisie (« 06 12 34 56 78 ») en E.164 (« +33612345678 »).

    Renvoie une chaîne vide si rien n'est saisi. Lève ValidationError si le
    numéro est illisible, n'existe pas ou n'est pas un portable.
    """
    texte = (texte or "").strip()
    if not texte:
        return ""
    try:
        numero = phonenumbers.parse(texte, region)
    except phonenumbers.NumberParseException as erreur:
        raise ValidationError(
            "Ce numéro est illisible. Écrivez-le comme 06 12 34 56 78 ou +33 6 12 34 56 78.",
            code="telephone_illisible",
        ) from erreur
    if not phonenumbers.is_valid_number(numero):
        raise ValidationError(
            "Ce numéro n'existe pas. Vérifiez les chiffres.", code="telephone_invalide"
        )
    if phonenumbers.number_type(numero) not in TYPES_PORTABLES:
        raise ValidationError(
            "Il faut un numéro de portable, pour pouvoir recevoir les SMS.",
            code="telephone_non_portable",
        )
    return phonenumbers.format_number(numero, phonenumbers.PhoneNumberFormat.E164)


def afficher_telephone(e164, region=REGION_PAR_DEFAUT):
    """Forme lisible : « 06 12 34 56 78 » pour la France, internationale sinon."""
    if not e164:
        return ""
    numero = phonenumbers.parse(e164, None)
    if phonenumbers.region_code_for_number(numero) == region:
        return phonenumbers.format_number(numero, phonenumbers.PhoneNumberFormat.NATIONAL)
    return phonenumbers.format_number(numero, phonenumbers.PhoneNumberFormat.INTERNATIONAL)


def masquer_telephone(e164, region=REGION_PAR_DEFAUT):
    """Cache les chiffres du milieu : « 06 •• •• •• 78 ».

    On garde le premier groupe (indicatif ou 06/07) et les deux derniers
    chiffres : assez pour reconnaître un numéro, pas pour l'appeler.
    """
    try:
        texte = afficher_telephone(e164, region)
    except phonenumbers.NumberParseException:
        texte = e164  # numéro illisible : on masque quand même ses chiffres
    if not texte:
        return ""
    debut = texte.find(" ")
    if debut == -1:
        debut = 2
    positions = [i for i, c in enumerate(texte) if c.isdigit() and i > debut]
    a_cacher = set(positions[:-2])
    return "".join("•" if i in a_cacher else c for i, c in enumerate(texte))
