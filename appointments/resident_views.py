"""Resident pages of the appointments (card T27): book, then see the meeting.

The Rendez-vous tab lists the meetings to come, with one button to book
(design card D2). Booking is its own page, in three numbered steps that are
links and one form (no script needed): the educator (or "le premier libre"),
the day, then the time and the reason, which only the educator of the
meeting can read. Writing to an educator lives under Messages.
"""

from datetime import datetime, time
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.cache import add_never_cache_headers
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from access.session_policy import is_resident

from . import booking, direct, reminders
from .availability import settings_of
from .models import Appointment, EducatorSettings

ANY = "libre"


def _choice(request, educators):
    """(educator or None for "le premier libre", key, known).

    ``known`` is False when the address names someone who is not (or no
    longer) an educator offering meetings.
    """
    key = request.POST.get("avec") or request.GET.get("avec") or ANY
    for educator in educators:
        if str(educator.pk) == key:
            return educator, key, True
    return None, ANY, key == ANY


def _day(value, days):
    """(day, slots, found): the first day with slots if ``value`` has none."""
    for day, slots in days:
        if day.isoformat() == value:
            return day, slots, True
    first = days[0] if days else (None, [])
    return first[0], first[1], not value


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
@require_http_methods(["GET", "HEAD", "POST"])
def overview(request):
    """The Rendez-vous tab: my meetings to come, and the button to book one.

    Until design card D2 this address was the booking form: a form opened
    before the change, or a bookmark with a choice, still reaches it.
    """
    if not is_resident(request.user):
        return redirect("home")
    if request.method == "POST":
        return book(request)
    if request.GET.get("avec") or request.GET.get("jour"):
        return redirect(f"{reverse('rdv:book')}?{request.GET.urlencode()}")
    return _page(
        render(
            request,
            "appointments/overview.html",
            {
                "active_nav": "appointments",
                "upcoming": booking.upcoming(request.user).select_related("educator"),
                "can_book": booking.educators().exists(),
            },
        )
    )


@login_required
@require_safe
def educators_to_write(request):
    """Choose who to write to: any active educator, even without open times (card T28)."""
    if not is_resident(request.user):
        return redirect("home")
    return _page(
        render(
            request,
            "appointments/educators.html",
            {"active_nav": "messages", "educators": direct.educators()},
        )
    )


@login_required
@require_http_methods(["GET", "POST"])
def book(request):
    if not is_resident(request.user):
        return redirect("home")
    educators = list(booking.educators())
    educator, key, known = _choice(request, educators)
    people = [educator] if educator else educators
    if request.method == "POST" and not known:
        # Never another educator than the one chosen, without saying it.
        messages.warning(
            request, "Cet éducateur ne propose plus de rendez-vous. Choisissez à nouveau."
        )
        return redirect("rdv:book")
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

    if not known:
        messages.info(request, "Cet éducateur ne propose plus de rendez-vous.")
    days = booking.days_with_slots(people)
    day, slots, found = _day(request.GET.get("jour", ""), days)
    times = _times(slots)
    wanted = request.GET.get("heure", "") if found else ""
    # The time asked in the link ("Le plus tôt"), if it is still free that day
    chosen = next(
        (s for s in times if timezone.localtime(s.start).strftime("%H%M") == wanted), None
    )
    if not found:
        messages.info(
            request, "Ce jour n'a plus de créneau libre : voici le premier jour possible."
        )
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
                "days": days,
                "day": day,
                "times": times,
                "wanted": wanted,
                "chosen": chosen,
                "first": first,
                "length": length,
                "reasons": Appointment.Reason.choices,
                "time_groups": [
                    ("Matin", [s for s in times if timezone.localtime(s.start).hour < 12]),
                    ("Après-midi", [s for s in times if timezone.localtime(s.start).hour >= 12]),
                ],
            },
        )
    )


def _reminder_text(meeting):
    """What the resident will get, never a promise of a reminder that will not come."""
    if meeting.status != Appointment.Status.CONFIRMED:
        return ""
    if not settings_of(meeting.educator).remind_residents:
        return ""
    if reminders.gets_day_before(meeting):
        return "Un rappel vous est envoyé la veille au soir et une heure avant."
    if reminders.gets_hour_before(meeting):
        return "Un rappel vous est envoyé une heure avant."
    return ""


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
            {
                "active_nav": "appointments",
                "meeting": meeting,
                "can_cancel": meeting.status == Appointment.Status.CONFIRMED
                and meeting.start > timezone.now(),
                "reminder": _reminder_text(meeting),
            },
        )
    )


@login_required
@sensitive_post_parameters("text")  # never in an error report
@require_http_methods(["GET", "POST"])
def write(request, educator_pk):
    """Direct messages with one educator (card T28)."""
    if not is_resident(request.user):
        return redirect("home")
    educator = get_object_or_404(direct.educators(), pk=educator_pk)
    conversation = direct.conversation_of(request.user, educator)
    text = ""
    if request.method == "POST":
        text = request.POST.get("text", "")
        try:
            direct.send(conversation, request.user, text, resident=request.user, educator=educator)
        except direct.MessageRefused as refused:
            messages.warning(request, str(refused))
        else:
            return redirect(reverse("rdv:write", args=[educator.pk]) + "#last-message")
    new_ids = direct.mark_read(conversation, request.user) if conversation else []
    return _page(
        render(
            request,
            "appointments/write.html",
            {
                "active_nav": "messages",
                "educator": educator,
                "reply_hours": settings_of(educator).reply_hours,
                "thread": conversation.messages.select_related("author") if conversation else [],
                "text": text,
                "max_length": direct.MAX_LENGTH,
                "new_ids": new_ids,
            },
        )
    )


@login_required
@require_POST
def cancel(request, pk):
    """The resident cancels their meeting (card T29); the educator is told."""
    meeting = get_object_or_404(
        Appointment.objects.select_related("educator"), pk=pk, resident=request.user
    )
    try:
        booking.cancel(meeting, request.user)
    except booking.AlreadyCancelled:
        pass  # a second click: the first one already said it
    except booking.CancelRefused as refused:
        messages.warning(request, str(refused))
    else:
        name = direct.first_name(meeting.educator)
        messages.success(request, f"Rendez-vous annulé. Nous prévenons {name}.")
    return redirect("rdv:detail", pk=meeting.pk)
