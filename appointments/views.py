"""Staff pages of the appointments (card T26: the weekly grid and the settings)."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.db.models import OuterRef, Prefetch, Subquery
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.cache import add_never_cache_headers
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.roles import Role
from housing.models import Stay
from ui.middleware import background

from . import availability, booking, direct
from .forms import AbsenceForm, SettingsForm
from .holidays import holiday_name
from .models import Absence, Appointment, Availability, Conversation, DirectMessage

PERMISSION = "accounts.manage_appointments"


def _report(request, count, short, settings):
    if not count:
        messages.warning(
            request,
            "Disponibilités enregistrées : aucun créneau ouvert, personne ne peut réserver.",
        )
        return
    messages.success(request, "Disponibilités enregistrées. Elles se répètent chaque semaine.")
    if short:
        many = len(short) > 1
        listed = ", ".join(str(row) for row in short)
        messages.warning(
            request,
            f"{len(short)} créneau{'x' if many else ''} trop court{'s' if many else ''} pour "
            f"un rendez-vous de {settings.slot_minutes} minutes : {listed}. "
            "Personne ne peut y réserver.",
        )


@login_required
@permission_required(PERMISSION, raise_exception=True)
@require_http_methods(["GET", "POST"])
def my_availability(request):
    """The weekly grid of the educator who is logged in, and their settings."""
    educator = request.user
    current = availability.settings_of(educator)
    form = SettingsForm(request.POST or None, instance=current)
    if request.method == "POST" and form.is_valid():
        # The settings and the grid together, or nothing (double click, two tabs).
        with transaction.atomic():
            availability.lock(educator)
            settings = form.save()
            count = availability.save_grid(educator, request.POST.getlist("cell"))
        _report(request, count, availability.too_short(educator, settings.slot_minutes), settings)
        return redirect("appointments:availability")
    if request.method == "POST":  # invalid settings: keep the cells being edited
        opened = {key for key in request.POST.getlist("cell") if key in availability.CELLS}
    else:
        opened = availability.open_cells(educator)
    days = [(day, Availability.Weekday(day).label) for day in availability.DAYS]
    rows = [
        {
            "time": moment,
            "full_hour": moment.minute == 0,
            "end": availability._add(moment, availability.STEP),
            "cells": [
                {"key": availability.cell_key(day, moment), "day": label} for day, label in days
            ],
        }
        for moment in availability.cell_times()
    ]
    response = render(
        request,
        "appointments/availability.html",
        {
            "active_nav": "appointments",
            "form": form,
            "days": days,
            "rows": rows,
            "opened": opened,
            # Only educators are offered to the residents (T27).
            "is_educator": educator.has_role(Role.EDUCATOR),
            "meetings": _meetings(educator),
            "cancelled": _cancelled(educator),
            "absences": Absence.objects.filter(
                educator=educator, last_day__gte=timezone.localdate()
            ),
            "absence_form": AbsenceForm(),
        },
    )
    # Names, rooms and reasons: never kept by the browser or a proxy.
    add_never_cache_headers(response)
    return response


def _meetings(educator):
    """The next meetings of the educator, with the room of each resident."""
    current = Stay.objects.current().select_related("room")
    meetings = list(
        Appointment.objects.filter(
            educator=educator, status=Appointment.Status.CONFIRMED, end__gt=timezone.now()
        )
        .select_related("resident")
        .prefetch_related(Prefetch("resident__stays", queryset=current, to_attr="current"))[:30]
    )
    now = timezone.now()
    for meeting in meetings:
        stays = meeting.resident.current
        meeting.room = stays[0].room.number if stays else ""
        meeting.holiday = holiday_name(timezone.localtime(meeting.start).date())
        meeting.can_cancel = meeting.start > now  # not once it has started
    return meetings


def _cancelled(educator):
    """Meetings still to come that the resident cancelled, or that a departure cancelled.

    The educator may have no device for the notification: the page says it too.
    """
    return (
        Appointment.objects.filter(
            educator=educator, status=Appointment.Status.CANCELLED, start__gt=timezone.now()
        )
        .exclude(cancelled_by=educator)
        .select_related("resident")
        .order_by("start")[:10]
    )


@login_required
@permission_required(PERMISSION, raise_exception=True)
@require_POST
def add_absence(request):
    form = AbsenceForm(request.POST)
    if form.is_valid():
        # Same lock as the bookings: none lands on a day being closed.
        with transaction.atomic():
            availability.lock(request.user)
            absence = form.save(commit=False)
            absence.educator = request.user
            absence.save()
        busy = Appointment.objects.filter(
            educator=request.user,
            status=Appointment.Status.CONFIRMED,
            start__date__gte=absence.first_day,
            start__date__lte=absence.last_day,
        ).count()
        messages.success(request, "Absence enregistrée : personne ne peut réserver ces jours-là.")
        if busy:
            who = "les personnes concernées" if busy > 1 else "la personne concernée"
            messages.warning(
                request, f"{busy} rendez-vous déjà pris pendant cette absence : prévenez {who}."
            )
    else:
        messages.warning(request, " ".join(e for errors in form.errors.values() for e in errors))
    return redirect("appointments:availability")


@login_required
@permission_required(PERMISSION, raise_exception=True)
@require_POST
def delete_absence(request, pk):
    get_object_or_404(Absence, pk=pk, educator=request.user).delete()
    messages.success(request, "Absence retirée.")
    return redirect("appointments:availability")


def _private(response):
    add_never_cache_headers(response)
    return response


@login_required
@permission_required(PERMISSION, raise_exception=True)
def conversations(request):
    """Direct messages of the educator who is logged in (card T28)."""
    last = DirectMessage.objects.filter(conversation=OuterRef("pk")).order_by("-sent_at", "-pk")
    found = (
        direct.with_unread(
            Conversation.objects.filter(educator=request.user).select_related("resident"),
            request.user,
        )
        .annotate(
            last_author=Subquery(last.values("author_id")[:1]),
            last_text=Subquery(last.values("text")[:1]),
        )
        # Unread first, then the most recent (design card D3).
        .order_by("-unread", "-updated_at")
    )
    return _private(
        render(
            request,
            "appointments/conversations.html",
            {"active_nav": "conversations", "conversations": found},
        )
    )


@login_required
@permission_required(PERMISSION, raise_exception=True)
@sensitive_post_parameters("text")  # never in an error report
@require_http_methods(["GET", "POST"])
def conversation(request, pk):
    # Only the educator of the conversation: the rest of the staff gets a 404.
    found = get_object_or_404(
        Conversation.objects.select_related("resident"), pk=pk, educator=request.user
    )
    text = ""
    if request.method == "POST":
        text = request.POST.get("text", "")
        try:
            direct.send(found, request.user, text)
        except direct.MessageRefused as refused:
            messages.warning(request, str(refused))
        else:
            return redirect(reverse("appointments:conversation", args=[found.pk]) + "#last-message")
    # Read only when the last messages are on screen, not an older page.
    before = direct.cursor(request)
    new_ids = direct.mark_read(found, request.user) if before is None else []
    stays = Stay.objects.current().filter(resident=found.resident).select_related("room")
    stay = stays.first()
    return _private(
        render(
            request,
            "appointments/conversation.html",
            {
                "active_nav": "conversations",
                "conversation": found,
                "room": stay.room.number if stay else "",
                "page": direct.page_of(found, before),
                "text": text,
                "max_length": direct.MAX_LENGTH,
                "reply_hours": availability.settings_of(request.user).reply_hours,
                "new_ids": new_ids,
                "left": not found.resident.is_active,
                "poll_url": reverse("appointments:conversation_newer", args=[found.pk]),
            },
        )
    )


def newer_messages(request, conversation, me):
    """The messages written after ?apres=, as list items (thread.js), or 204.

    They are on screen as soon as they arrive: the other person's are read.
    Also used by the resident's page (resident_views.write_newer).
    """
    after = direct.after_id(request)
    if conversation is None or after is None:
        return _private(HttpResponse(status=400))
    found = direct.newer_than(conversation, after)
    if not found:
        return _private(HttpResponse(status=204))
    new_ids = direct.mark_read(conversation, me, among=found)
    # No request given: the context processors (menu counters...) are not needed here.
    html = render_to_string(
        "appointments/_thread_items.html", {"messages": found, "me": me, "new_ids": new_ids}
    )
    return _private(HttpResponse(html))


@background
@login_required
@permission_required(PERMISSION, raise_exception=True)
@require_GET
def conversation_newer(request, pk):
    found = get_object_or_404(Conversation, pk=pk, educator=request.user)
    return newer_messages(request, found, request.user)


@login_required
@permission_required(PERMISSION, raise_exception=True)
@require_POST
def cancel_meeting(request, pk):
    """The educator cancels one of their meetings (card T29); the resident is told."""
    meeting = get_object_or_404(Appointment, pk=pk, educator=request.user)
    try:
        booking.cancel(meeting, request.user)
    except booking.AlreadyCancelled:
        pass  # a second click: the first one already said it
    except booking.CancelRefused as refused:
        messages.warning(request, str(refused))
    else:
        messages.success(request, "Rendez-vous annulé. La personne est prévenue.")
    return redirect("appointments:availability")
