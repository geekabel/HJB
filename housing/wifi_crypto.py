"""Encryption of the wifi passwords (card T15).

A wifi password must be shown again later (to the resident, T16), so it is
encrypted, not hashed. Fernet (cryptography library) gives authenticated
encryption: without the key, nobody can read or change a stored password.

Keys come from settings.WIFI_ENCRYPTION_KEYS (environment variable
DJANGO_WIFI_KEYS in production). MultiFernet encrypts with the first key and
decrypts with any of them: to change the key, put the new one first, run
`python manage.py rotate_wifi_keys`, then remove the old one.

Docs: https://cryptography.io/en/latest/fernet/
"""

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class WifiDecryptionError(Exception):
    """The stored password cannot be read with the configured keys."""


def _fernet():
    keys = settings.WIFI_ENCRYPTION_KEYS
    if not keys:
        raise ImproperlyConfigured("Aucune clé de chiffrement du wifi (DJANGO_WIFI_KEYS).")
    try:
        return MultiFernet([Fernet(key) for key in keys])
    except ValueError as error:
        raise ImproperlyConfigured(f"Clé de chiffrement du wifi invalide : {error}") from error


def encrypt(password):
    """Return the Fernet token (text) for this password."""
    return _fernet().encrypt(password.encode()).decode()


def decrypt(token):
    """Return the password stored in this token."""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as error:
        raise WifiDecryptionError("The wifi password cannot be decrypted.") from error


def rotate(token):
    """Encrypt the token again with the first key (keeps its timestamp)."""
    try:
        return _fernet().rotate(token.encode()).decode()
    except InvalidToken as error:
        raise WifiDecryptionError("The wifi password cannot be decrypted.") from error
