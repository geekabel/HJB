"""All the ways an account logs in: passkeys, and app codes for staff (card T14c).

A lost phone, a departure or a new activation removes all of them at once:
an old device never keeps a way in.
"""

from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp_webauthn.utils import get_credential_model


def passkeys(user):
    return get_credential_model().objects.filter(user=user)


def app_codes(user, confirmed=True):
    return TOTPDevice.objects.filter(user=user, confirmed=confirmed)


def remove_all(user, *, keep=None):
    """Delete the passkeys and the app codes of ``user``, except ``keep``. Return the count.

    Each deletion closes the sessions of the account and forgets its
    notification devices (post_delete signals in access and push).
    """
    count = 0
    for queryset in (passkeys(user), TOTPDevice.objects.filter(user=user)):
        if keep is not None and isinstance(keep, queryset.model):
            queryset = queryset.exclude(pk=keep.pk)
        count += queryset.count()
        queryset.delete()
    return count
