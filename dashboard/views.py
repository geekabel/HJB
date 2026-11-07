"""Staff dashboard (card T35): the day at a glance, what is late, what
leaves soon, and which floor is next for a room visit."""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.utils import timezone
from django.utils.cache import add_never_cache_headers
from django.views.decorators.http import require_safe

from . import services


def allowed(user):
    """Every staff member; each part depends on the permissions. The front
    desk and the administration start here; maintenance and educators keep
    their own first page (access/views.py home)."""
    return user.has_perm("accounts.access_staff_area")


@login_required
@require_safe
def dashboard(request):
    user = request.user
    if not allowed(user):
        raise PermissionDenied
    now = timezone.now()
    handles_reports = user.has_perm("accounts.manage_reports")
    sends = user.has_perm("accounts.send_messages")
    response = render(
        request,
        "dashboard/dashboard.html",
        {
            "active_nav": "dashboard",
            "now": now,
            "figures": services.figures(user, now),
            "late_reports": services.late_reports(now) if handles_reports else [],
            "visit_replies": services.visit_replies(now) if sends else [],
            "scheduled": services.scheduled_messages(now) if sends else [],
            "rotation": services.rotation() if sends else [],
            "sends": sends,
            "handles_reports": handles_reports,
        },
    )
    add_never_cache_headers(response)
    return response
