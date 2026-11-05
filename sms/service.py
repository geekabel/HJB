"""Single entry point to send an SMS: ``send_sms(number, text)``.

The active provider comes from the ``SMS`` setting (same shape as Django's
e-mail settings):

    SMS = {"BACKEND": "sms.providers.ovh.OvhProvider", "OPTIONS": {...}}
"""

import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.module_loading import import_string

from accounts.phone import mask_phone, normalize_phone, validate_e164

from .providers.base import ConfigurationError, SendError, SmsError
from .segments import analyze

logger = logging.getLogger(__name__)

# Beyond this, the message costs a lot and is hard to read on a phone.
MAX_SEGMENTS = 6


def active_provider():
    setting = getattr(settings, "SMS", {})
    try:
        provider_class = import_string(setting["BACKEND"])
    except (KeyError, ImportError) as error:
        raise ConfigurationError(f"Réglage SMS invalide : {error}") from error
    return provider_class(**setting.get("OPTIONS", {}))


def send_sms(number, text):
    """Send an SMS to the E.164 number ``number``. Return a SendResult.

    Raise SmsError (or a subclass) on failure. Check its ``temporary`` and
    ``uncertain`` attributes before any new attempt.
    """
    try:
        validate_e164(number)
        # A real mobile number (phonenumbers), not only "+ and digits".
        valid = normalize_phone(number) == number
    except ValidationError:
        valid = False
    if not valid:
        raise SendError("Le numéro n'est pas un portable au format international.")
    text = (text or "").strip()
    if not text:
        raise SendError("Le message est vide.")
    info = analyze(text)
    if info.segments > MAX_SEGMENTS:
        raise SendError(f"Le message est trop long ({info.segments} SMS, {MAX_SEGMENTS} au plus).")

    provider = active_provider()
    missing = provider.missing_options()
    if missing:
        raise ConfigurationError(
            f"Fournisseur {provider.name} : options manquantes ({', '.join(missing)})."
        )
    # Logs never contain the full number or the text.
    try:
        result = provider.send(number, text)
    except SmsError as error:
        logger.warning(
            "SMS sending failed via %s to %s: %s",
            provider.name,
            mask_phone(number),
            error,
        )
        raise
    logger.info(
        "SMS sent via %s to %s (%s, %d segment(s), id %s)",
        provider.name,
        mask_phone(number),
        info.encoding,
        info.segments,
        result.message_id,
    )
    return result
