"""Open sessions of an account: find them and close them.

Django docs:
- database-backed sessions: https://docs.djangoproject.com/en/6.1/topics/http/sessions/#using-database-backed-sessions
"""

from importlib import import_module

from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.models import Session
from django.utils import timezone


def session_keys_for(user):
    """Keys of this user's open sessions.

    Reads the session table: works for the "db" engine (current setting)
    and "cached_db". With another engine, this function must be reviewed.
    In any case, the password hash change closes the remaining
    sessions on their next request.
    """
    user_id = str(getattr(user, "pk", user))  # account or id
    return [
        session.session_key
        for session in Session.objects.filter(expire_date__gt=timezone.now()).iterator()
        if session.get_decoded().get(SESSION_KEY) == user_id
    ]


def close_sessions(keys):
    """Delete these sessions with the configured engine (database and any cache)."""
    engine = import_module(settings.SESSION_ENGINE)
    for key in keys:
        engine.SessionStore(session_key=key).delete()
    return len(keys)


def close_all(user, *, keep=None):
    """Close all sessions of this account, except the key ``keep``. Return their count."""
    return close_sessions([key for key in session_keys_for(user) if key != keep])
