"""Staff pages of the appointments (card T26: the weekly grid and the settings)."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from accounts.roles import Role

from . import availability
from .forms import SettingsForm
from .models import Availability

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
        },
    )
