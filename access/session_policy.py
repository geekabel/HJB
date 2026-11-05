"""Session length and recent passkey confirmation (card T13).

- A resident logged in with a passkey keeps the session for 90 days without
  activity: they mostly use their own phone.
- Staff keep the default length (SESSION_COOKIE_AGE, 12 hours).
- Sensitive actions (wifi password, adding a passkey...) need a passkey
  verification less than 10 minutes old: a long session on a stolen phone
  is not enough.

Django docs: https://docs.djangoproject.com/en/6.1/topics/http/sessions/#django.contrib.sessions.backends.base.SessionBase.set_expiry
"""

import time
from datetime import timedelta

from django.conf import settings

RESIDENT_SESSION_LENGTH = timedelta(days=90)
CONFIRMATION_WINDOW = timedelta(minutes=10)
CONFIRMED_AT_KEY = "passkey_confirmed_at"


def is_resident(user):
    """Same rule as User.objects.residents(): no role and no staff access."""
    return not (user.is_staff or user.is_superuser or user.has_staff_role)


def open_session(request, user):
    """Call it after each successful passkey verification."""
    length = (
        RESIDENT_SESSION_LENGTH
        if is_resident(user)
        else timedelta(seconds=settings.SESSION_COOKIE_AGE)
    )
    request.session.set_expiry(int(length.total_seconds()))
    request.session[CONFIRMED_AT_KEY] = time.time()


def confirmed_recently(request):
    """True if the passkey was used less than 10 minutes ago in this session."""
    moment = request.session.get(CONFIRMED_AT_KEY)
    if not isinstance(moment, (int, float)):
        return False
    return 0 <= time.time() - moment < CONFIRMATION_WINDOW.total_seconds()
