"""State of the activation journey, kept in the session (not logged in yet).

After an accepted code, the session records the person, the code used and
the start time. The journey (phone, then passkey) must be finished within
the hour. It also stops as soon as the front desk gives the person a new
code (a stolen code does not keep control) or if the person leaves.
"""

import time

from access.session_policy import is_resident
from accounts.models import ActivationCode, User

KEY = "activation_journey"
DURATION = 60 * 60  # seconds


def start(request, activation_code):
    # New session key: nothing is left from an earlier session (fixation).
    request.session.cycle_key()
    request.session[KEY] = {
        "user": activation_code.user_id,
        "code": activation_code.pk,
        "started_at": time.time(),
    }


def current_person(request):
    """The person whose activation is in progress, or None (no journey, or ended)."""
    data = request.session.get(KEY)
    if not data:
        return None
    person = User.objects.filter(pk=data["user"], is_active=True).first()
    code = ActivationCode.objects.filter(pk=data.get("code")).first()
    replaced = (
        code is None
        or code.user_id != data["user"]
        or ActivationCode.objects.filter(
            user_id=data["user"], created_at__gt=code.created_at
        ).exists()
    )
    # The code must match the account: a front desk code for a resident,
    # an administrator code for staff (card T14). An account whose status
    # changed since the code was issued stops here.
    wrong_kind = person is not None and code is not None and code.for_staff == is_resident(person)
    if (
        time.time() - data.get("started_at", 0) > DURATION
        or person is None
        or replaced
        or wrong_kind
    ):
        del request.session[KEY]
        return None
    return person


def remember(request, key, value):
    """Record a completed step (for example "phone_verified")."""
    data = request.session[KEY]
    data[key] = value
    request.session[KEY] = data  # assigned again so that the session is saved


def pop(request, key):
    """Remove a value from the journey and save the session right away.

    Used for the passkey creation state: even if the next step fails, it
    cannot be used again (no replay).
    """
    data = request.session.get(KEY) or {}
    value = data.pop(key, None)
    if KEY in request.session:
        request.session[KEY] = data
    request.session.save()
    return value


def step_done(request, key):
    return bool(request.session.get(KEY, {}).get(key))


def finish(request):
    request.session.pop(KEY, None)
