from django.core.exceptions import ImproperlyConfigured

from .vapid import application_server_key


def _public_key():
    try:
        return application_server_key()
    except ImproperlyConfigured:
        return ""


def push(request):
    """The public VAPID key, for app.js (computed only if a template uses it)."""
    return {"push_public_key": _public_key}
