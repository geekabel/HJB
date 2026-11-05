"""Staff pages of the appointments (card T26: the weekly grid and the settings)."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from accounts.roles import Role
from housing.models import Stay

from . import availability
from .forms import AbsenceForm, SettingsForm
from .holidays import holiday_name
from .models import Absence, Appointment, Availability

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
    return render(
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
            "absences": Absence.objects.filter(
                educator=educator, last_day__gte=timezone.localdate()
            ),
            "absence_form": AbsenceForm(),
        },
    )


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
    for meeting in meetings:
        stays = meeting.resident.current
        meeting.room = stays[0].room.number if stays else ""
        meeting.holiday = holiday_name(timezone.localtime(meeting.start).date())
    return meetings


@login_required
@permission_required(PERMISSION, raise_exception=True)
@require_POST
def add_absence(request):
    form = AbsenceForm(request.POST)
    if form.is_valid():
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
