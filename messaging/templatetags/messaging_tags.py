from datetime import timedelta

from django import template
from django.utils import timezone
from django.utils.formats import date_format

register = template.Library()


@register.filter
def get_item(mapping, key):
    """{{ answers|get_item:user_id }}: a value of a dict in a template."""
    return mapping.get(key) if mapping else None


WEEKDAYS = ("Lun.", "Mar.", "Mer.", "Jeu.", "Ven.", "Sam.", "Dim.")


@register.filter
def short_when(value):
    """Date of a message in the inbox: "09:12", "Hier", "Lun.", "5 novembre"."""
    if not value:
        return ""
    moment = timezone.localtime(value)
    day, today = moment.date(), timezone.localdate()
    if day == today:
        return f"{moment:%H:%M}"
    if day == today - timedelta(days=1):
        return "Hier"
    if today - timedelta(days=7) < day < today:
        return WEEKDAYS[day.weekday()]
    return date_format(day, "j F" if day.year == today.year else "j F Y")
