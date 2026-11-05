"""Reactions to departures and to passkey deletions.

Django docs: model signals (post_delete) and transaction.on_commit
https://docs.djangoproject.com/en/6.1/ref/signals/#post-delete
https://docs.djangoproject.com/en/6.1/topics/db/transactions/#performing-actions-after-commit
"""

from django.db import transaction
from django_otp_webauthn.utils import get_credential_model

from accounts.sessions import close_all


def remove_passkeys_on_departure(sender, resident, **kwargs):
    """Called inside the departure transaction. The passkey count goes to the audit log."""
    passkeys = get_credential_model().objects.filter(user=resident)
    count = passkeys.count()
    passkeys.delete()
    return {"passkeys_removed": count}


def close_sessions_after_delete(sender, instance, **kwargs):
    """A deleted passkey (admin site, lost phone, departure) closes the sessions of the account.

    Otherwise, the lost device would stay logged in until the end of its
    session: the session does not depend on the passkey. We close after the
    transaction commits, so nothing is closed if the deletion is rolled back.
    """
    user_id = instance.user_id  # the account itself may be being deleted
    transaction.on_commit(lambda: close_all(user_id))
