"""Account activation, resident side (mockup R0).

Step 1: code given by the front desk (T11). Step 2: phone (T12).
Step 3: passkey (T13).
"""

import json
import logging
import time

from django.contrib import messages
from django.contrib.auth import login
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from django_otp import login as otp_login
from django_otp_webauthn.exceptions import OTPWebAuthnApiError
from django_otp_webauthn.utils import get_credential_model, rewrite_exceptions

from access import session_policy
from access.errors import error_response
from access.webauthn import ActivationWebAuthnHelper
from accounts import phone_verification
from accounts.activation_codes import ActivationError, redeem_code
from accounts.models import User
from accounts.sessions import close_sessions, session_keys_for
from audit.models import Action
from audit.service import client_ip, log_action

from . import journey
from .forms import ActivationCodeForm, SmsCodeForm

webauthn_logger = logging.getLogger("django_otp_webauthn")

# Code entry failures in this browser, over the last hour.
FAILURES_KEY = "activation_failures"


@never_cache
def enter_code(request):
    form = ActivationCodeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        # Times of the failures in the last hour, in this browser.
        failures = [t for t in request.session.get(FAILURES_KEY, []) if time.time() - t < 3600]
        try:
            code = redeem_code(form.cleaned_data["code"], client_ip(request), len(failures))
        except ActivationError as error:
            if error.code == "invalid":
                failures.append(time.time())
            request.session[FAILURES_KEY] = failures
            form.add_error("code", str(error))
        else:
            journey.start(request, code)
            return redirect("activation:phone")
    return render(request, "activation/enter_code.html", {"form": form, "step": 1})


@never_cache
def phone(request):
    """Step 2: an SMS code proves that the person really has this phone (card T12)."""
    person = journey.current_person(request)
    if person is None:
        messages.info(request, "Pour commencer, saisissez le code remis par l'accueil.")
        return redirect("activation:enter_code")
    if journey.step_done(request, "phone_verified") and person.phone_is_verified:
        return redirect("activation:passkey")

    form = SmsCodeForm()
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "send":
                phone_verification.send_code(person)
                messages.success(request, "Code envoyé. Il peut mettre une minute à arriver.")
                return redirect("activation:phone")
            if action == "verify":
                form = SmsCodeForm(request.POST)
                if form.is_valid():
                    phone_verification.check_code(person, form.cleaned_data["code"])
                    journey.remember(request, "phone_verified", True)
                    return redirect("activation:passkey")
        except phone_verification.VerificationError as error:
            if action == "verify":
                form.add_error("code", str(error))
            else:
                messages.warning(request, str(error))
                return redirect("activation:phone")

    latest = phone_verification.latest(person)
    code_sent = bool(
        latest
        and latest.verified_at is None
        and latest.expires_at > timezone.now()
        and latest.phone == person.phone
    )
    return render(
        request,
        "activation/phone.html",
        {
            "step": 2,
            "person": person,
            "form": form,
            "code_sent": code_sent,
            "resend_at": phone_verification.resend_available_at(person),
        },
    )


@never_cache
def wrong_number(request):
    """The "not my number" page: only the front desk can fix the number.

    A plain information page: viewing it (GET) changes nothing.
    """
    return render(request, "activation/wrong_number.html", {"step": 2})


# State of the WebAuthn ceremony, kept in the journey between begin and complete.
PASSKEY_STATE = "passkey_state"
PASSKEY_BACKEND = "django_otp_webauthn.backends.WebAuthnBackend"


def _ready_person(request):
    """The person of the journey, if their phone is verified (checked again each time)."""
    person = journey.current_person(request)
    if (
        person is not None
        and journey.step_done(request, "phone_verified")
        and person.phone_is_verified
    ):
        return person
    return None


@never_cache
def passkey(request):
    """Step 3: passkey creation (card T13)."""
    person = _ready_person(request)
    if person is None:
        if journey.current_person(request):
            return redirect("activation:phone")
        return redirect("activation:enter_code")
    config = {
        "mode": "register",
        "begin": reverse("activation:passkey_begin"),
        "complete": reverse("activation:passkey_complete"),
        "next": "",
    }
    return render(
        request,
        "activation/passkey.html",
        {"step": 3, "person": person, "config": config},
    )


class JourneyEnded(Exception):
    """The journey is no longer valid (departure, new code...): everything is cancelled."""


JOURNEY_ENDED = (
    "Votre activation a expiré. Recommencez avec le code remis par l'accueil, "
    "ou demandez-en un nouveau."
)


@require_POST
@never_cache
def passkey_begin(request):
    """Passkey creation options, for navigator.credentials.create()."""
    person = _ready_person(request)
    if person is None:
        return error_response("journey", 403, JOURNEY_ENDED)
    options, state = ActivationWebAuthnHelper(request).register_begin(user=person)
    journey.remember(request, PASSKEY_STATE, state)
    return JsonResponse(options)


@require_POST
@never_cache
def passkey_complete(request):
    """Check and save the passkey, replace the old ones, then log the person in."""
    state = journey.pop(request, PASSKEY_STATE)  # single use, even on error
    person = _ready_person(request)
    if person is None:
        return error_response("journey", 403, JOURNEY_ENDED)
    if not state:
        return error_response("invalid_state", 400)
    try:
        data = json.loads(request.body)
    except ValueError:
        return error_response("malformed_request", 400)

    try:
        with transaction.atomic():
            # Lock on the account: a creation, a departure or a new code run
            # one after the other. Everything is checked again once the lock is held.
            User.objects.select_for_update().get(pk=person.pk)
            person = _ready_person(request)
            if person is None:
                raise JourneyEnded
            with rewrite_exceptions(logger=webauthn_logger):
                new_passkey = ActivationWebAuthnHelper(request).register_complete(
                    user=person, state=state, data=data
                )
            # Recovery (lost or changed phone): the old passkeys no longer work.
            previous = get_credential_model().objects.filter(user=person).exclude(pk=new_passkey.pk)
            count = previous.count()
            previous.delete()
            log_action(
                Action.PASSKEY_CREATED,
                actor=person,
                target=person,
                details={"previous_removed": count},
                request=request,
            )
    except JourneyEnded:
        return error_response("journey", 403, JOURNEY_ENDED)
    except IntegrityError:
        # Passkey id already saved (replayed or forged response).
        return error_response("credential_exists", 422)
    except OTPWebAuthnApiError as error:
        return error_response(error.code, error.status_code)

    # The other sessions of the person (old phone) are closed.
    other_sessions = session_keys_for(person)
    login(request, person, backend=PASSKEY_BACKEND)  # new session key, last_login set
    otp_login(request, new_passkey)
    close_sessions(other_sessions)
    journey.finish(request)
    session_policy.open_session(request, person)
    return JsonResponse({"id": new_passkey.pk, "redirect_url": reverse("home")})
