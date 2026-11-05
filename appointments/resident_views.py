"""Resident pages of the appointments (card T27): book, then see the meeting.

The steps are links and one form (no script needed): the educator (or "le
premier libre"), the day, then the time and the reason, which only the
educator of the meeting can read.
"""

from datetime import datetime, time
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.cache import add_never_cache_headers
from django.views.decorators.http import require_http_methods, require_safe

from access.session_policy import is_resident

from . import booking
from .models import Appointment, EducatorSettings

ANY = "libre"


def _choice(request, educators):
    """The educator chosen (or None for "le premier libre") and the key in the address."""
    key = request.GET.get("avec") or request.POST.get("avec") or ANY
    for educator in educators:
        if str(educator.pk) == key:
            return educator, key
    return None, ANY


def _day(value, days):
    for day, slots in days:
        if day.isoformat() == value:
            return day, slots
    return days[0] if days else (None, [])


def _times(slots):
    """One entry per start time (several educators may be free at once)."""
    seen = {}
    for slot in slots:
        seen.setdefault(timezone.localtime(slot.start), slot)
    return list(seen.values())


def _page(response):
    add_never_cache_headers(response)
    return response


@login_required
@require_http_methods(["GET", "POST"])
def book(request):
    if not is_resident(request.user):
        return redirect("home")
    educators = list(booking.educators())
    educator, key = _choice(request, educators)
    people = [educator] if educator else educators
    if request.method == "POST":
        try:
            day = datetime.strptime(request.POST.get("jour", ""), "%Y-%m-%d").date()
            hhmm = request.POST.get("heure", "")
            start = timezone.make_aware(datetime.combine(day, time(int(hhmm[:2]), int(hhmm[2:]))))
        except (ValueError, TypeError):
            messages.warning(request, "Choisissez un jour et une heure.")
        else:
            try:
                meeting = booking.book(request.user, start, people, request.POST.get("motif", ""))
            except booking.BookingRefused as refused:
                messages.warning(request, str(refused))
            else:
                messages.success(request, "Rendez-vous confirmé.")
                return redirect("rdv:detail", pk=meeting.pk)
        query = urlencode({"avec": key, "jour": request.POST.get("jour", "")[:10]})
        return redirect(f"{reverse('rdv:book')}?{query}")

    days = booking.days_with_slots(people)
    day, slots = _day(request.GET.get("jour", ""), days)
    times = _times(slots)
    wanted = request.GET.get("heure", "")
    first = days[0][1][0] if days else None
    length = None
    if educator is not None:
        found = EducatorSettings.objects.filter(educator=educator).first()
        length = found.slot_minutes if found else 30
    return _page(
        render(
            request,
            "appointments/book.html",
            {
                "active_nav": "appointments",
                "educators": educators,
                "educator": educator,
                "key": key,
                "any_key": ANY,
                "days": days[:10],
                "day": day,
                "times": times,
                "wanted": wanted,
                "first": first,
                "length": length,
                "reasons": Appointment.Reason.choices,
                "upcoming": booking.upcoming(request.user),
            },
        )
    )


@login_required
@require_safe
def detail(request, pk):
    meeting = get_object_or_404(
        Appointment.objects.select_related("educator"), pk=pk, resident=request.user
    )
    return _page(
        render(
            request,
            "appointments/detail.html",
            {"active_nav": "appointments", "meeting": meeting},
        )
    )
