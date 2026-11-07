"""Staff pages of the reports (card T31): the board, one report, its steps.

For the roles that handle reports (Accueil, Maintenance, Administration:
permission manage_reports). The board has four columns, from new to done;
on a phone they follow one another. Late reports come first.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Count
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.cache import add_never_cache_headers
from django.views.decorators.http import require_POST, require_safe

from . import handling
from .models import Report, ReportPhoto
from .staff_forms import AssignForm, DoneForm, PlanForm, initial_plan

PERMISSION = "accounts.manage_reports"

COLUMNS = [
    (Report.Status.NEW, "Nouveau"),
    (Report.Status.ACKNOWLEDGED, "Pris en charge"),
    (Report.Status.SCHEDULED, "Planifié"),
    (Report.Status.DONE, "Fait, à confirmer"),
]

FILTERS = [("all", "Tous"), ("mine", "Confiés à moi"), ("late", "En retard")]


def _private(response):
    add_never_cache_headers(response)
    return response


def _active():
    return (
        Report.objects.filter(status__in=[status for status, _ in COLUMNS])
        .select_related("room", "assigned_to")
        .annotate(photo_count=Count("photos"))
    )


@login_required
@permission_required(PERMISSION, raise_exception=True)
@require_safe
def board(request):
    now = timezone.now()
    key = request.GET.get("show", "all")
    if key not in dict(FILTERS):
        key = "all"
    reports = list(_active())
    late_count = sum(report.is_late(now) for report in reports)
    if key == "mine":
        reports = [r for r in reports if r.assigned_to_id == request.user.pk]
    elif key == "late":
        reports = [r for r in reports if r.is_late(now)]
    for report in reports:
        report.late = report.is_late(now)
        report.delay = report.delay_text(now)
        report.close_on = report.done_at + Report.CLOSE_AFTER if report.done_at else None

    # Late first, then the closest due date; planned visits by their time,
    # done work from the oldest.
    def order(report):
        if report.status == Report.Status.SCHEDULED and report.intervention_start:
            return (False, report.intervention_start)
        if report.status == Report.Status.DONE:
            return (False, report.updated_at)
        return (not report.late, report.due_at)

    reports.sort(key=order)
    columns = [
        (status, label, [r for r in reports if r.status == status]) for status, label in COLUMNS
    ]
    return _private(
        render(
            request,
            "reports/board.html",
            {
                "active_nav": "reports",
                "columns": columns,
                "filters": FILTERS,
                "current": key,
                "late_count": late_count,
                "now": now,
            },
        )
    )


def _detail_context(request, report, **forms):
    report.late = report.is_late()
    report.delay = report.delay_text()
    return {
        "active_nav": "reports",
        "report": report,
        "events": report.events.select_related("author"),
        "assign_form": forms.get("assign_form")
        or AssignForm(initial={"assignee": report.assigned_to_id or request.user.pk}),
        # Prefixes: both forms have a "note" field, their ids must differ.
        "plan_form": forms.get("plan_form")
        or PlanForm(initial=initial_plan(report), prefix="plan"),
        "done_form": forms.get("done_form") or DoneForm(prefix="done"),
        "can_act": report.status in (*Report.WAITING, Report.Status.SCHEDULED),
    }


def _get(pk):
    return get_object_or_404(
        Report.objects.select_related("resident", "room__floor", "assigned_to").prefetch_related(
            "photos"
        ),
        pk=pk,
    )


@login_required
@permission_required(PERMISSION, raise_exception=True)
@require_safe
def detail(request, pk):
    report = _get(pk)
    return _private(render(request, "reports/staff_detail.html", _detail_context(request, report)))


def _step(request, pk, action):
    """Run one step; a refusal is shown as a warning on the report."""
    report = _get(pk)
    try:
        text = action(report)
    except handling.StepRefused as refused:
        messages.warning(request, str(refused))
    else:
        if text:
            messages.success(request, text)
    return redirect("reports_staff:detail", pk=report.pk)


@login_required
@permission_required(PERMISSION, raise_exception=True)
@require_POST
def take(request, pk):
    def action(report):
        handling.take(report, request.user)
        return "Vous vous en occupez. Le résident est prévenu."

    response = _step(request, pk, action)
    if request.POST.get("from") == "board":
        return redirect("reports_staff:board")
    return response


@login_required
@permission_required(PERMISSION, raise_exception=True)
@require_POST
def assign(request, pk):
    form = AssignForm(request.POST)
    if not form.is_valid():
        messages.warning(request, "Choisissez une personne de la liste.")
        return redirect("reports_staff:detail", pk=pk)

    def action(report):
        handling.assign(report, request.user, form.cleaned_data["assignee"])
        person = form.cleaned_data["assignee"]
        return f"Confié à {person.get_full_name() or person.get_username()}."

    return _step(request, pk, action)


@login_required
@permission_required(PERMISSION, raise_exception=True)
@require_POST
def plan(request, pk):
    form = PlanForm(request.POST, prefix="plan")
    if not form.is_valid():
        report = _get(pk)
        context = _detail_context(request, report, plan_form=form)
        return _private(render(request, "reports/staff_detail.html", context, status=400))

    def action(report):
        start, end = form.moments()
        handling.plan(report, request.user, start, end, form.cleaned_data["note"])
        return "Intervention planifiée. Le résident est prévenu."

    return _step(request, pk, action)


@login_required
@permission_required(PERMISSION, raise_exception=True)
@require_POST
def done(request, pk):
    form = DoneForm(request.POST, prefix="done")
    if not form.is_valid():
        report = _get(pk)
        context = _detail_context(request, report, done_form=form)
        return _private(render(request, "reports/staff_detail.html", context, status=400))

    def action(report):
        handling.done(report, request.user, form.cleaned_data["note"])
        return "Marqué comme fait. Le résident doit confirmer."

    return _step(request, pk, action)


@login_required
@permission_required(PERMISSION, raise_exception=True)
@require_safe
def photo(request, pk):
    found = get_object_or_404(ReportPhoto, pk=pk)
    try:
        response = FileResponse(found.image.open("rb"), content_type="image/jpeg")
    except FileNotFoundError as missing:
        raise Http404 from missing
    response.headers["Content-Disposition"] = "inline"
    return _private(response)
