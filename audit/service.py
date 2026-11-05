"""Write to the audit log.

from audit.models import Action
from audit.service import log_action

log_action(Action.ROLES_CHANGED, target=user, details={...}, request=request)
"""

from django.contrib.contenttypes.models import ContentType

from .models import AuditEntry


def client_ip(request):
    """Client address as Django sees it (REMOTE_ADDR, docs HttpRequest.META).

    Behind a proxy, this is the proxy address: the setting is planned for
    deployment (card T38). We never read X-Forwarded-For here, because a
    client can make it up.
    """
    if request is None:
        return None
    return request.META.get("REMOTE_ADDR") or None


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
