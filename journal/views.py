from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.shortcuts import render

from .models import Action, EntreeJournal

ENTREES_PAR_PAGE = 50


@login_required
@permission_required("comptes.voir_journal", raise_exception=True)
def liste(request):
    """Journal d'audit, réservé au rôle Administration. Pagination : doc « Pagination »."""
    entrees = EntreeJournal.objects.all()
    action = request.GET.get("action", "")
    if action in Action.values:
        entrees = entrees.filter(action=action)
    else:
        action = ""
    page = Paginator(entrees, ENTREES_PAR_PAGE).get_page(request.GET.get("page"))
    return render(
        request,
        "journal/liste.html",
        {"page_obj": page, "actions": Action.choices, "action": action, "actif": "journal"},
    )
