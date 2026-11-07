"""Cut the access of an account (lost or stolen phone), card T13."""

from django.db import transaction
from django.utils import timezone

from accounts.models import ActivationCode
from accounts.sessions import close_sessions, session_keys_for
from audit.models import Action
from audit.service import log_action

from . import credentials


def cut_access(user, *, by=None, request=None):
    """Delete the passkeys and app codes, cancel the pending code, close the sessions.

    The person can come back with a new activation code (and, if their
    SIM card is lost, a phone number fixed on their profile).
    Returns (passkeys deleted, sessions closed).
    """
    sessions = session_keys_for(user)
    with transaction.atomic():
        type(user).objects.select_for_update().get(pk=user.pk)
        passkey_count = credentials.remove_all(user)
        ActivationCode.objects.valid().filter(user=user).update(cancelled_at=timezone.now())
        session_count = close_sessions(sessions)
        log_action(
            Action.ACCESS_CUT,
            actor=by,
            target=user,
            details={"passkeys_removed": passkey_count, "sessions_closed": session_count},
            request=request,
        )
    return passkey_count, session_count
