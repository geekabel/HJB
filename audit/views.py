from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.shortcuts import render

from .models import Action, AuditEntry

ENTRIES_PER_PAGE = 50


@login_required
@permission_required("accounts.view_audit_log", raise_exception=True)
def entry_list(request):
    """Audit log, for the Administration role only. Pagination: Django docs "Pagination"."""
    entries = AuditEntry.objects.all()
    action = request.GET.get("action", "")
    if action in Action.values:
        entries = entries.filter(action=action)
    else:
        action = ""
    page = Paginator(entries, ENTRIES_PER_PAGE).get_page(request.GET.get("page"))
    return render(
        request,
        "audit/list.html",
        {"page_obj": page, "actions": Action.choices, "action": action, "active_nav": "audit"},
    )
