"""Resident pages of the reports (card T30): report a problem, see my reports.

The form is a task screen (design card D5): on a phone it covers the tab bar
and keeps its "Envoyer" button at the bottom. It reminds the number to call
at once for a serious problem (settings.EMERGENCY_PHONE).
"""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.cache import add_never_cache_headers
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from access.session_policy import is_resident

from . import handling, photos, service
from .forms import ReportForm
from .models import Report, ReportEvent, ReportPhoto

# How soon the staff take the report in hand, shown under each urgency
DELAY_TEXT = {
    Report.Urgency.CAN_WAIT: "Sous 7 jours",
    Report.Urgency.ANNOYING: "Sous 48 h",
    Report.Urgency.URGENT: "Sous 4 h",
}


def _page(response):
    add_never_cache_headers(response)
    return response


def _emergency():
    return {"emergency_phone": settings.EMERGENCY_PHONE}


@login_required
@require_safe
def overview(request):
    """The Signaler tab: my reports, the open ones first."""
    if not is_resident(request.user):
        return redirect("home")
    reports = list(Report.objects.filter(resident=request.user))
    return _page(
        render(
            request,
            "reports/overview.html",
            {
                "active_nav": "reports",
                "open_reports": [r for r in reports if r.is_open],
                "closed_reports": [r for r in reports if not r.is_open][:5],
                **_emergency(),
            },
        )
    )


@login_required
@require_http_methods(["GET", "POST"])
def new(request):
    if not is_resident(request.user):
        return redirect("home")
    room = service.room_of(request.user)
    form = ReportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and room is not None and form.is_valid():
        try:
            report = service.create(request.user, form.cleaned_data)
        except service.NoRoom:
            room = None
        else:
            messages.success(request, "Signalement envoyé.")
            return redirect("reports:detail", pk=report.pk)
    return _page(
        render(
            request,
            "reports/new.html",
            {
                "active_nav": "reports",
                "form": form,
                "room": room,
                "max_photos": photos.MAX_PHOTOS,
                # A browser cannot keep chosen files: after an error, say so.
                "photos_lost": bool(request.FILES),
                "categories": [
                    (value, label, Report.ICONS[value]) for value, label in Report.Category.choices
                ],
                "urgencies": [
                    (value, label, DELAY_TEXT[value]) for value, label in Report.Urgency.choices
                ],
                "access_choices": ReportForm.ACCESS_CHOICES,
                **_emergency(),
            },
        )
    )


@login_required
@require_safe
def detail(request, pk):
    report = get_object_or_404(
        Report.objects.select_related("room").prefetch_related("photos"),
        pk=pk,
        resident=request.user,
    )
    events = list(
        report.events.exclude(type=ReportEvent.Type.ASSIGNED)
        .select_related("author")
        .order_by("-created_at", "-pk")
    )
    # The word of the staff with the last planned visit or the work done
    last = next(
        (
            e
            for e in events
            if e.type in (ReportEvent.Type.SCHEDULED, ReportEvent.Type.INTERVENTION)
        ),
        None,
    )
    remind_from = report.can_remind_from()
    return _page(
        render(
            request,
            "reports/detail.html",
            {
                "active_nav": "reports",
                "report": report,
                "events": events,
                "staff_note": last.note if last else "",
                "remind_from": remind_from,
                "can_remind": remind_from is not None and remind_from <= timezone.now(),
                "close_on": report.done_at + Report.CLOSE_AFTER if report.done_at else None,
                **_emergency(),
            },
        )
    )


def _own(request, pk):
    return get_object_or_404(Report, pk=pk, resident=request.user)


def _step(request, pk, action, done_text):
    report = _own(request, pk)
    try:
        action(report)
    except handling.StepRefused as refused:
        messages.warning(request, str(refused))
    else:
        messages.success(request, done_text)
    return redirect("reports:detail", pk=report.pk)


@login_required
@require_POST
def confirm(request, pk):
    return _step(
        request, pk, lambda r: handling.confirm(r, request.user), "Merci ! Le signalement est clos."
    )


@login_required
@require_POST
def reopen(request, pk):
    note = request.POST.get("note", "")[:300]
    return _step(
        request,
        pk,
        lambda r: handling.reopen(r, request.user, note),
        "C'est noté : l'équipe est prévenue.",
    )


@login_required
@require_POST
def remind(request, pk):
    return _step(request, pk, lambda r: handling.remind(r, request.user), "L'équipe est relancée.")


@login_required
@require_safe
def photo(request, pk):
    """A photo of my report. Never cached: a phone can be shared."""
    found = get_object_or_404(ReportPhoto, pk=pk, report__resident=request.user)
    try:
        response = FileResponse(found.image.open("rb"), content_type="image/jpeg")
    except FileNotFoundError as missing:
        raise Http404 from missing
    response.headers["Content-Disposition"] = "inline"
    return _page(response)
