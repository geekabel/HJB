"""Staff pages of the appointments (card T26: the weekly grid and the settings)."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from accounts.roles import Role

from . import availability
from .forms import SettingsForm
from .models import Availability

PERMISSION = "accounts.manage_appointments"


@login_required
@permission_required(PERMISSION, raise_exception=True)
@require_http_methods(["GET", "POST"])
def my_availability(request):
    """The weekly grid of the educator who is logged in, and their settings."""
    educator = request.user
    current = availability.settings_of(educator)
    form = SettingsForm(request.POST or None, instance=current)
    if request.method == "POST" and form.is_valid():
        form.save()
        count = availability.save_grid(educator, request.POST.getlist("cell"))
        if count:
            messages.success(
                request, "Disponibilités enregistrées. Elles se répètent chaque semaine."
            )
        else:
            messages.warning(
                request,
                "Disponibilités enregistrées : aucun créneau ouvert, personne ne peut réserver.",
            )
        return redirect("appointments:availability")
    opened = availability.open_cells(educator)
    times = availability.cell_times()
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
        for moment in times
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
