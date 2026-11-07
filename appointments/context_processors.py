"""Unread direct messages, on the "Rendez-vous" entry of the menus (card T28)."""

from . import direct


def unread(request):
    # A function: the template calls it only where it shows the counter.
    return {"unread_direct": lambda: direct.unread_count(request.user)}
