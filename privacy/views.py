"""The page "Vos données" (card T36): open to all, logged in or not, so
that it can be read before activating an account."""

from django.shortcuts import render
from django.views.decorators.http import require_safe

from . import retention


def _duration(number):
    """365 -> "1 an", 180 -> "6 mois", 30 -> "30 jours"."""
    if number % 365 == 0:
        years = number // 365
        return f"{years} an{'s' if years > 1 else ''}"
    if number % 30 == 0 and number >= 60:
        return f"{number // 30} mois"
    return f"{number} jour{'s' if number > 1 else ''}"


@require_safe
def data(request):
    from access.session_policy import is_resident
    from residence.models import ResidenceSettings

    found = ResidenceSettings.load()
    durations = {key: _duration(found.retention_days(key)) for key in retention.KINDS}
    contact = found.privacy_contact.strip()

    user = request.user
    staff = user.is_authenticated and not is_resident(user)
    active_nav = "account_section" if user.is_authenticated else ""
    return render(
        request,
        "privacy/data.html",
        {
            "layout": "ui/staff.html" if staff else "ui/resident.html",
            "active_nav": active_nav,
            "durations": durations,
            "organization": found,
            "contact": contact,
            "contact_is_email": "@" in contact,
        },
    )
