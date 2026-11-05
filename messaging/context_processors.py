"""Number of unread messages, for the resident navigation bar (card T23)."""

from . import inbox


def unread(request):
    # A function: the template calls it only where it shows the counter,
    # so the other pages make no query.
    return {"unread_messages": lambda: inbox.unread_count(request.user)}
