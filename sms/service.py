"""Single entry point to send an SMS: ``send_sms(number, text)``.

The active provider comes from the ``SMS`` setting (same shape as Django's
e-mail settings):

    SMS = {"BACKEND": "sms.providers.ovh.OvhProvider", "OPTIONS": {...}}
"""

import dataclasses
import logging
import os

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.db.models import F
from django.utils import timezone
from django.utils.module_loading import import_string

from accounts.phone import mask_phone, normalize_phone, validate_e164

from .providers.base import ConfigurationError, SendError, SmsError
from .segments import analyze

logger = logging.getLogger(__name__)

# Beyond this, the message costs a lot and is hard to read on a phone.
MAX_SEGMENTS = 6
# Used until the residence settings exist (first migrate).
DEFAULT_DAILY_LIMIT = 100
# The last SMS of the day are kept for the codes (activation, verification):
# a big sending never locks people out of their account until midnight.
KEPT_FOR_CODES = 10


class DailyLimitReached(SendError):
    """The daily limit of the residence settings is reached: not sent."""


def _build(setting):
    try:
        provider_class = import_string(setting["BACKEND"])
    except (KeyError, ImportError) as error:
        raise ConfigurationError(f"Réglage SMS invalide : {error}") from error
    return provider_class(**setting.get("OPTIONS", {}))


def configured_provider():
    """The provider of the server's settings (SMS), without the database."""
    return _build(getattr(settings, "SMS", {}))


def provider_named(name):
    """A provider of SMS_PROVIDERS, its options read from the environment."""
    if name == "paused":
        from .providers.disabled import PausedProvider

        return PausedProvider()
    backend, variables = settings.SMS_PROVIDERS[name]
    options = {key: os.environ.get(variable, "") for key, variable in variables.items()}
    return _build({"BACKEND": backend, "OPTIONS": options})


def ready_providers():
    """The real providers whose keys are all on the server (card T37b)."""
    ready = []
    for name in ("ovh", "smsgate"):
        try:
            if not provider_named(name).missing_options():
                ready.append(name)
        except ConfigurationError:
            continue
    return ready


def _chosen():
    """The choice of the administration (residence settings), or ""."""
    from residence.models import ResidenceSettings

    try:
        choice = ResidenceSettings.objects.filter(pk=1).values_list("sms_provider", flat=True)
        return choice.first() or ""
    except DatabaseError:  # table not created yet (first migrate)
        return ""


def sms_paused():
    """True if the administration cut the SMS (residence settings)."""
    return _chosen() == "paused"


def active_provider():
    """The provider chosen in the settings of the residence, else the
    server's. A chosen provider whose keys went missing falls back to the
    server's one: the choice never sends with half a configuration."""
    choice = _chosen()
    if choice == "paused" or (choice and choice in ready_providers()):
        return provider_named(choice)
    return configured_provider()


def daily_limit():
    """The most SMS (segments) that may leave in one day."""
    from residence.models import ResidenceSettings

    try:
        limit = (
            ResidenceSettings.objects.filter(pk=1).values_list("sms_daily_limit", flat=True).first()
        )
    except DatabaseError:  # table not created yet (first migrate)
        limit = None
    return limit or DEFAULT_DAILY_LIMIT


def sent_today():
    """SMS (segments) sent today, local time."""
    from .models import SmsDailyUsage

    usage = SmsDailyUsage.objects.filter(day=timezone.localdate())
    return usage.values_list("segments", flat=True).first() or 0


def left_today():
    """SMS that a message may still use today (the codes' share aside)."""
    return max(0, daily_limit() - KEPT_FOR_CODES - sent_today())


def _reserve(segments, *, code):
    """Count ``segments`` for today, or raise DailyLimitReached.

    One UPDATE checks and counts at once: two workers sending at the same
    time never go over the limit together. Return the day counted.
    """
    from .models import SmsDailyUsage

    day = timezone.localdate()
    limit = daily_limit() - (0 if code else KEPT_FOR_CODES)
    SmsDailyUsage.objects.get_or_create(day=day)
    counted = SmsDailyUsage.objects.filter(day=day, segments__lte=limit - segments).update(
        segments=F("segments") + segments
    )
    if not counted:
        logger.warning("SMS daily limit reached (%d)", limit)
        raise DailyLimitReached(
            f"Limite de {limit} SMS par jour atteinte : plus aucun SMS avant minuit."
        )
    return day


def _release(day, segments):
    """The SMS did not leave: it no longer counts."""
    from .models import SmsDailyUsage

    SmsDailyUsage.objects.filter(day=day, segments__gte=segments).update(
        segments=F("segments") - segments
    )


def send_sms(number, text, *, code=False):
    """Send an SMS to the E.164 number ``number``. Return a SendResult.

    ``code``: an activation or verification code, which may use the last
    SMS of the day (KEPT_FOR_CODES). Never call inside transaction.atomic():
    the count of the day would stay locked during the sending, and a
    rollback would forget an SMS that left.

    Raise SmsError (or a subclass) on failure. Check its ``temporary`` and
    ``uncertain`` attributes before any new attempt. DailyLimitReached: the
    daily limit of the residence settings is reached.
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
    # A cut service refuses anyway: it says why, and counts nothing.
    day = None if provider.name == "disabled" else _reserve(info.segments, code=code)
    # Logs never contain the full number or the text.
    try:
        result = provider.send(number, text)
    except SmsError as error:
        if day and not error.uncertain:  # an SMS that may have left still counts
            _release(day, info.segments)
        logger.warning(
            "SMS sending failed via %s to %s: %s",
            provider.name,
            mask_phone(number),
            error,
        )
        raise
    result = dataclasses.replace(result, tracked=bool(provider.tracks_delivery()))
    logger.info(
        "SMS sent via %s to %s (%s, %d segment(s), id %s)",
        provider.name,
        mask_phone(number),
        info.encoding,
        info.segments,
        result.message_id,
    )
    return result
