"""Reactions to departures and to passkey deletions.

Django docs: model signals (post_delete) and transaction.on_commit
https://docs.djangoproject.com/en/6.1/ref/signals/#post-delete
https://docs.djangoproject.com/en/6.1/topics/db/transactions/#performing-actions-after-commit
"""

from django.db import transaction

from accounts.sessions import close_all

from . import credentials


def remove_passkeys_on_departure(sender, resident, **kwargs):
    """Called inside the departure transaction. The passkey count goes to the audit log."""
    return {"passkeys_removed": credentials.remove_all(resident)}


def close_sessions_after_delete(sender, instance, **kwargs):
    """A deleted passkey or app code (admin site, lost phone, departure) closes the sessions.

    Otherwise, the lost device would stay logged in until the end of its
    session: the session does not depend on the passkey. We close after the
    transaction commits, so nothing is closed if the deletion is rolled back.
    """
    user_id = instance.user_id  # the account itself may be being deleted
    transaction.on_commit(lambda: close_all(user_id))
