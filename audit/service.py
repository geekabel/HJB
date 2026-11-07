"""Write to the audit log.

from audit.models import Action
from audit.service import log_action

log_action(Action.ROLES_CHANGED, target=user, details={...}, request=request)
"""

import ipaddress

from django.conf import settings
from django.contrib.contenttypes.models import ContentType

from .models import AuditEntry


def client_ip(request):
    """The client's address (card T38).

    REMOTE_ADDR, unless the request comes from a trusted proxy
    (TRUSTED_PROXIES: Caddy on the same machine). Then X-Forwarded-For is
    read from the right: each proxy appends the address it saw, so the
    first address that is not a trusted proxy is the client. A client can
    put anything at the left of the header; that part is never read.
    """
    if request is None:
        return None
    remote = request.META.get("REMOTE_ADDR") or None
    trusted = set(getattr(settings, "TRUSTED_PROXIES", []))
    if remote not in trusted:
        return remote
    for value in reversed(request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")):
        value = value.strip()
        try:
            ipaddress.ip_address(value)
        except ValueError:
            return remote  # a broken header: keep what we know for sure
        if value not in trusted:
            return value
    return remote


def _label(target):
    """Return "Awa Koné (awa.kone)" for an account with a name, else str(target)."""
    name = target.get_full_name() if hasattr(target, "get_full_name") else ""
    return f"{name} ({target.get_username()})" if name else str(target)


def log_action(action, *, actor=None, target=None, details=None, request=None):
    """Add an entry to the audit log and return it.

    Without ``actor``, use the logged-in user of ``request`` if there is one.
    """
    if actor is None and request is not None and request.user.is_authenticated:
        actor = request.user
    entry = AuditEntry(
        action=action,
        actor=actor,
        actor_label=actor.get_username() if actor else "",
        details=details or {},
        ip_address=client_ip(request),
    )
    if target is not None:
        entry.target_type = ContentType.objects.get_for_model(target)
        entry.target_id = str(target.pk)
        entry.target_label = _label(target)[:200]
    entry.save()
    return entry
