"""French typography in templates (design card D4).

``pluriel``: the French plural mark. Unlike Django's ``pluralize``, 0 takes
the singular: "0 notification", "1 message", "2 messages".
``jour``: the day above a group of direct messages (design card D5).
Docs: https://docs.djangoproject.com/en/6.1/howto/custom-template-tags/#writing-custom-template-filters
"""

from datetime import timedelta

from django import template
from django.utils import timezone
from django.utils.formats import date_format

register = template.Library()


@register.filter(is_safe=False)
def pluriel(value, suffix="s"):
    """``suffix`` when ``value`` (a number, or a list) is more than 1, else ""."""
    try:
        count = len(value) if hasattr(value, "__len__") and not isinstance(value, str) else value
        return suffix if abs(float(count)) > 1 else ""
    except (TypeError, ValueError):
        return ""


@register.filter
def jour(value):
    """The day of ``value`` (a datetime) for a list of messages: "Aujourd'hui",
    "Hier", or "jeudi 5 novembre" (with the year if it is not this year)."""
    if not value:
        return ""
    day = timezone.localtime(value).date()
    today = timezone.localdate()
    if day == today:
        return "Aujourd'hui"
    if day == today - timedelta(days=1):
        return "Hier"
    return date_format(day, "l j F" if day.year == today.year else "l j F Y")
