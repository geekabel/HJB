"""Staff area: list and profile of the residents (mockup P5).

Viewing: permission ``accounts.view_residents`` (Accueil, Éducateurs,
Administration). Creation, change, import and departure:
``accounts.manage_residents`` (Accueil, Administration).
"""

import logging
import secrets
import time
from datetime import timedelta
from urllib.parse import urlencode

import segno
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ImproperlyConfigured, PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, OuterRef, Prefetch, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.cache import add_never_cache_headers
from django.utils.formats import date_format
from django.utils.safestring import mark_safe
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_GET, require_POST
from django_otp_webauthn.utils import get_credential_model

from access.decorators import recent_confirmation_required
from access.session_policy import confirmed_recently
from accounts.activation_codes import (
    VALIDITY,
    activation_state,
    issue_code,
    send_code_by_sms,
)
from accounts.models import ACCOUNT_STATE_FILTERS, AccountState, User
from accounts.phone import mask_phone
from accounts.roles import Role
from audit.models import Action
from audit.service import log_action
from housing import wifi
from housing.models import (
    WIFI_REMINDER_DAYS,
    WIFI_RENEWAL_WARNING_DAYS,
    Floor,
    Stay,
    WifiAccess,
    WifiSettings,
)
from housing.services import current_stay
from housing.wifi_crypto import WifiDecryptionError
from push.models import PushSubscription

from .bulk_import import (
    HEADERS,
    FileError,
    analyze,
    from_session,
    has_wifi_columns,
    read_file,
    run_import,
    to_session,
)
from .departure import (
    cancel_planned_departure,
    has_left,
    plan_departure,
    record_departure,
    record_return,
)
from .forms import DepartureForm, ImportForm, ResidentForm, ReturnForm, WifiAccessForm
from .models import ResidentImport

logger = logging.getLogger(__name__)

RESIDENTS_PER_PAGE = 50
NO_ROOM = "none"


def _current_stays():
    # The active wifi access of each room comes in one more query (card T15).
    return (
        Stay.objects.current()
        .select_related("room__floor")
        .prefetch_related(
            Prefetch(
                "room__wifi_accesses",
                queryset=WifiAccess.objects.active(),
                to_attr="active_wifi",
            )
        )
    )


def _residents():
    return (
        User.objects.residents()
        .prefetch_related(
            Prefetch("stays", queryset=_current_stays(), to_attr="current_stays"),
            "groups",
        )
        .order_by("last_name", "first_name", "pk")
    )


def _former():
    """Former residents: account disabled and no current stay.

    An account that is disabled but still housed stays in the list: its
    departure is not finished (the room is not free).
    """
    current = Stay.objects.filter(resident=OuterRef("pk"), departure__isnull=True)
    return Q(is_active=False) & ~Exists(current)


def _filter(residents, search, floor, account):
    current = Stay.objects.filter(resident=OuterRef("pk"), departure__isnull=True)
    for word in search.split():
        residents = residents.filter(
            Q(first_name__icontains=word)
            | Q(last_name__icontains=word)
            | Exists(current.filter(room__number__iexact=word))
        )
    if floor == NO_ROOM:
        residents = residents.exclude(Exists(current))
    elif floor:
        residents = residents.filter(Exists(current.filter(room__floor_id=floor)))
    if account:
        residents = residents.filter(ACCOUNT_STATE_FILTERS[account])
    return residents


@login_required
@permission_required("accounts.view_residents", raise_exception=True)
def resident_list(request):
    search = request.GET.get("q", "").strip()[:100]
    floors = list(Floor.objects.all())
    floor = request.GET.get("floor", "")
    if floor != NO_ROOM and floor not in {str(f.pk) for f in floors}:
        floor = ""
    can_manage = request.user.has_perm("accounts.manage_residents")
    states = AccountState.choices
    if not can_manage:
        # Educators only see current residents (data minimisation).
        states = [choice for choice in states if choice[0] != AccountState.DISABLED]
    account = request.GET.get("account", "")
    if account not in dict(states):
        account = ""

    everyone = User.objects.residents()
    counts = everyone.aggregate(
        total=Count("pk"),
        former=Count("pk", filter=_former()),
        **{state: Count("pk", filter=q) for state, q in ACCOUNT_STATE_FILTERS.items()},
    )
    counts["current"] = counts["total"] - counts["former"]
    residents = _filter(_residents(), search, floor, account)
    if account != AccountState.DISABLED:
        # Former residents only show up with the "Désactivé" filter.
        residents = residents.exclude(_former())
    page = Paginator(residents, RESIDENTS_PER_PAGE).get_page(request.GET.get("page"))
    for resident in page:
        resident.stay = resident.current_stays[0] if resident.current_stays else None
        resident.wifi = (
            resident.stay.room.active_wifi[0]
            if resident.stay and resident.stay.room.active_wifi
            else None
        )
        resident.is_moderator = Role.MODERATOR in resident.roles

    filters = request.GET.copy()
    filters.pop("page", None)
    return render(
        request,
        "residents/list.html",
        {
            "active_nav": "residents",
            "page_obj": page,
            "counts": counts,
            "search": search,
            "floors": floors,
            "floor": floor,
            "states": states,
            "can_manage": can_manage,
            "account": account,
            "filters_active": bool(search or floor or account),
            "query_string": filters.urlencode(),
            "renewal_count": WifiAccess.objects.to_renew().count(),
        },
    )


@login_required
@permission_required("accounts.view_residents", raise_exception=True)
def wifi_renewals(request):
    """Wifi accesses to renew: ending within 30 days, or already ended (card T17)."""
    devices = PushSubscription.objects.filter(user=OuterRef("resident"))
    current = Stay.objects.current().select_related("resident").annotate(has_device=Exists(devices))
    accesses = (
        WifiAccess.objects.to_renew()
        .select_related("room")
        .prefetch_related(Prefetch("room__stays", queryset=current, to_attr="current_stays"))
        .order_by("expires_on", "room__number")
    )
    for access in accesses:
        stay = access.room.current_stays[0] if access.room.current_stays else None
        access.resident = stay.resident if stay else None
        # What the staff can do about the reminder: tell the resident in person if needed.
        if access.reminder_sent_at:
            access.reminder_state = "sent"
        elif access.is_expired:
            access.reminder_state = "expired"
        elif access.days_left > WIFI_REMINDER_DAYS:
            access.reminder_state = "planned"
            access.reminder_on = access.expires_on - timedelta(days=WIFI_REMINDER_DAYS)
        elif stay and not stay.resident.wifi_expiry_reminder:
            access.reminder_state = "off"
        elif stay and not stay.has_device:
            access.reminder_state = "no_device"
        else:
            access.reminder_state = "pending"
    return render(
        request,
        "residents/wifi_renewals.html",
        {
            "active_nav": "residents",
            "accesses": accesses,
            "warning_days": WIFI_RENEWAL_WARNING_DAYS,
            "reminder_days": WIFI_REMINDER_DAYS,
        },
    )


def _confirm_first(request, resident):
    """A redirect to the passkey confirmation, or None if it is recent.

    Card T37: a new activation code, a cut access or a new phone number
    could hand over a resident's account. They need a passkey (or app code)
    used less than 10 minutes ago, like the wifi passwords.
    """
    if confirmed_recently(request):
        return None
    messages.info(request, "Confirmez d'abord votre identité, puis recommencez.")
    back = reverse("residents:detail", args=[resident.pk])
    return redirect(f"{reverse('access:confirm')}?{urlencode({'next': back})}")


def _resident_form(request, resident):
    form = ResidentForm(request.POST or None, instance=resident)
    before = resident.phone if resident.pk else ""
    if request.method == "POST" and form.is_valid():
        # The number as saved (normalized), not as typed: "06 12..." for the
        # same number is no change.
        phone_changed = bool(resident.pk) and form.instance.phone != before
        # Removing a number hands nothing over: only a new number asks.
        if phone_changed and form.instance.phone and not confirmed_recently(request):
            form.needs_confirmation = True  # the view sends to the confirmation
            return form, None
        try:
            with transaction.atomic():
                resident = form.save_resident()
                if phone_changed:
                    log_action(
                        Action.PHONE_CHANGED,
                        actor=request.user,
                        target=resident,
                        details={"before": mask_phone(before), "after": mask_phone(resident.phone)},
                        request=request,
                    )
        except ValidationError as error:
            form.add_stay_errors(error)
        except IntegrityError:
            # Two staff members chose the same room at the same moment.
            form.add_error("room", "Cette chambre vient d'être attribuée. Choisissez-en une autre.")
        else:
            return form, resident
    return form, None


@login_required
@permission_required("accounts.manage_residents", raise_exception=True)
def create(request):
    form, resident = _resident_form(request, User())
    if resident:
        messages.success(request, f"La fiche de {resident.get_full_name()} est créée.")
        return redirect("residents:detail", pk=resident.pk)
    return render(
        request,
        "residents/detail.html",
        {"active_nav": "residents", "form": form, "resident": None},
    )


@login_required
@permission_required("accounts.view_residents", raise_exception=True)
def detail(request, pk):
    resident = get_object_or_404(User.objects.residents(), pk=pk)
    can_manage = request.user.has_perm("accounts.manage_residents")
    if not can_manage and has_left(resident):
        raise Http404  # former residents: only for the front desk and the administration
    form = None
    if can_manage:
        form, saved = _resident_form(request, resident)
        if getattr(form, "needs_confirmation", False):
            messages.info(
                request,
                "Le numéro n'est pas changé. Confirmez d'abord votre identité, puis recommencez.",
            )
            back = reverse("residents:detail", args=[resident.pk])
            return redirect(f"{reverse('access:confirm')}?{urlencode({'next': back})}")
        if saved:
            messages.success(request, "Les modifications sont enregistrées.")
            return redirect("residents:detail", pk=resident.pk)
        resident.refresh_from_db()  # the form may have changed the object without saving it
    elif request.method == "POST":
        raise PermissionDenied
    stay = current_stay(resident)
    return render(
        request,
        "residents/detail.html",
        {
            "active_nav": "residents",
            "form": form,
            "resident": resident,
            "stay": stay,
            "stays": resident.stays.select_related("room__floor"),
            "wifi_access": wifi.current_access(stay.room) if stay else None,
            "activation": activation_state(resident),
            "code_token": activation_code_token(request, resident)
            if request.user.has_perm("accounts.issue_activation_codes")
            else "",
            # Latest passkey: shown with the activation, to the front desk and the administration.
            "passkey": get_credential_model()
            .objects.filter(user=resident)
            .order_by("-created_at")
            .first()
            if request.user.has_perm("accounts.issue_activation_codes")
            else None,
            "last_departure": resident.stays.filter(departure__isnull=False)
            .order_by("-departure")
            .values_list("departure", flat=True)
            .first(),
        },
    )


@login_required
@permission_required("accounts.manage_residents", raise_exception=True)
def departure(request, pk):
    """Departure (card T09): confirmation page, because the action closes the account."""
    resident = get_object_or_404(User.objects.residents(), pk=pk)
    if resident.pk == request.user.pk:
        raise PermissionDenied
    if has_left(resident):
        messages.info(request, "Le départ de cette personne est déjà enregistré.")
        return redirect("residents:detail", pk=resident.pk)
    stay = current_stay(resident)
    form = DepartureForm(request.POST or None, stay=stay)
    if (
        request.method == "POST"
        and form.is_valid()
        and (form.cleaned_data["departure"] > timezone.localdate())
    ):
        on = form.cleaned_data["departure"]
        try:
            plan_departure(resident, on, by=request.user, request=request)
        except ValidationError as error:
            form.add_error("departure", error.messages)
        else:
            name = resident.get_full_name() or resident.get_username()
            when = date_format(on, "l j F Y")
            messages.success(
                request,
                f"Départ de {name} prévu le {when}. Il sera enregistré automatiquement "
                "ce jour-là à midi : compte désactivé, accès wifi coupé.",
            )
            return redirect("residents:detail", pk=resident.pk)
    elif request.method == "POST" and form.is_valid():
        try:
            had_wifi = stay is not None and wifi.current_access(stay.room) is not None
            ended = record_departure(resident, form.cleaned_data["departure"], request=request)
        except ValidationError as error:
            if error.code == "already_left":
                messages.info(request, error.messages[0])
                return redirect("residents:detail", pk=resident.pk)
            form.add_error("departure", error.messages)
        else:
            name = resident.get_full_name() or resident.get_username()
            text = f"Le départ de {name} est enregistré. Son compte est désactivé."
            if ended is not None and had_wifi:
                text += (
                    f" L'accès wifi de la chambre {ended.room.number} est coupé : "
                    "changez-le sur le réseau avant l'arrivée du prochain résident."
                )
            messages.success(request, text)
            return redirect("residents:detail", pk=resident.pk)
    return render(
        request,
        "residents/departure.html",
        {"active_nav": "residents", "resident": resident, "stay": stay, "form": form},
    )


@require_POST
@login_required
@permission_required("accounts.manage_residents", raise_exception=True)
def cancel_planned_departure_view(request, pk):
    resident = get_object_or_404(User.objects.residents(), pk=pk)
    if cancel_planned_departure(resident, by=request.user, request=request):
        messages.success(request, "Départ prévu annulé.")
    return redirect("residents:detail", pk=resident.pk)


@login_required
@permission_required("accounts.manage_residents", raise_exception=True)
def return_view(request, pk):
    """Return of a former resident: choose their room, then give them a code."""
    resident = get_object_or_404(User.objects.residents(), pk=pk)
    if not has_left(resident):
        return redirect("residents:detail", pk=resident.pk)
    form = ReturnForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            record_return(resident, data["room"], data["arrival"], request=request)
        except (ValidationError, IntegrityError) as error:
            error_messages = getattr(error, "messages", ["Cette chambre vient d'être prise."])
            form.add_error(None, error_messages)
        else:
            messages.success(
                request,
                "Le retour est enregistré et le compte réactivé. "
                "Générez un code d'activation pour la personne.",
            )
            return redirect("residents:detail", pk=resident.pk)
    return render(
        request,
        "residents/return.html",
        {"active_nav": "residents", "resident": resident, "form": form},
    )


CODE_TOKENS_KEY = "activation_code_tokens"
MAX_TOKENS = 10


def activation_code_token(request, resident):
    """Single-use token for the "Générer un code" button of the profile.

    Reloading the code page sends the same token, already used: no new
    code replaces the one already handed over. The code is never kept in
    plain text, neither in the database nor in the session.
    """
    token = secrets.token_urlsafe(16)
    tokens = request.session.get(CODE_TOKENS_KEY, [])[-(MAX_TOKENS - 1) :]
    request.session[CODE_TOKENS_KEY] = [*tokens, [token, resident.pk]]
    return token


@require_POST
@login_required
@permission_required("accounts.issue_activation_codes", raise_exception=True)
def cut_access(request, pk):
    """Lost or stolen phone: the device is logged out right away (card T13)."""
    from access.services import cut_access as cut_user_access

    resident = get_object_or_404(User.objects.residents(), pk=pk)
    if confirm := _confirm_first(request, resident):
        return confirm
    passkeys, sessions = cut_user_access(resident, by=request.user, request=request)
    sp, ss = ("s" if passkeys > 1 else ""), ("s" if sessions > 1 else "")
    messages.success(
        request,
        f"Accès coupé : {passkeys} clé{sp} d'accès supprimée{sp}, {sessions} session{ss} "
        f"fermée{ss}. Vérifiez le numéro de téléphone, puis générez un nouveau code.",
    )
    return redirect("residents:detail", pk=resident.pk)


@require_POST
@login_required
@permission_required("accounts.issue_activation_codes", raise_exception=True)
def activation_code(request, pk):
    """Issue a code and show it only once, on a printable page that is never cached."""
    resident = get_object_or_404(User.objects.residents(), pk=pk)
    if confirm := _confirm_first(request, resident):
        return confirm
    tokens = request.session.get(CODE_TOKENS_KEY, [])
    expected = [request.POST.get("token", ""), resident.pk]
    if expected not in tokens:
        messages.info(
            request,
            "Ce code a déjà été généré : il reste valable. "
            "S'il ne s'est pas affiché ou s'il est perdu, générez-en un nouveau.",
        )
        return redirect("residents:detail", pk=resident.pk)
    request.session[CODE_TOKENS_KEY] = [t for t in tokens if t != expected]
    if not resident.is_active:
        messages.info(request, "Ce compte est désactivé : enregistrez d'abord le retour.")
        return redirect("residents:detail", pk=resident.pk)
    code = issue_code(resident, by=request.user, request=request)
    return activation_sheet(
        request, resident, code, reverse("residents:detail", args=[resident.pk])
    )


def activation_sheet(request, user, code, back_url):
    """Printable sheet with the code, never cached. Also used for staff accounts (T14)."""
    address = request.build_absolute_uri(reverse("activation:enter_code"))
    qr = segno.make_qr(f"{address}#{code}", error="m").svg_inline(
        scale=4, title=f"Code QR pour activer le compte de {user.get_full_name()}"
    )
    response = render(
        request,
        "residents/activation_code.html",
        {
            "active_nav": "residents",
            "resident": user,
            "code": code,
            "address": address,
            "expires_at": timezone.now() + VALIDITY,
            "qr": mark_safe(qr),  # SVG made by segno from our own link
            "back_url": back_url,
        },
    )
    add_never_cache_headers(response)
    return response


# --- Wifi access of the room (card T15) ----------------------------------------

WIFI_TOKENS_KEY = "wifi_form_tokens"
WIFI_NOT_CONFIGURED = (
    "Le chiffrement du wifi n'est pas configuré sur le serveur (DJANGO_WIFI_KEYS). "
    "Prévenez la personne qui l'administre."
)


def _wifi_token(request, resident, stay):
    """Single-use token of the wifi form, tied to the person and to the room.

    A reload never records (or generates) twice, and a form opened before a
    change of room cannot record on the new room.
    """
    token = secrets.token_urlsafe(16)
    tokens = request.session.get(WIFI_TOKENS_KEY, [])[-(MAX_TOKENS - 1) :]
    request.session[WIFI_TOKENS_KEY] = [*tokens, [token, resident.pk, stay.pk]]
    return token


def _resident_room(request, pk):
    """The resident and their current stay, or a message if they have no room."""
    resident = get_object_or_404(User.objects.residents(), pk=pk)
    stay = current_stay(resident)
    if stay is None:
        messages.info(request, "Cette personne n'a pas de chambre : pas d'accès wifi à gérer.")
    return resident, stay


def _never_cached(response):
    add_never_cache_headers(response)
    return response


@sensitive_post_parameters("password")
@sensitive_variables("password")
@login_required
@permission_required("accounts.manage_residents", raise_exception=True)
@recent_confirmation_required
def wifi_access(request, pk):
    """Record the wifi access of the resident's room: typed, or generated."""
    resident, stay = _resident_room(request, pk)
    if stay is None:
        return redirect("residents:detail", pk=resident.pk)
    current = wifi.current_access(stay.room)
    form = WifiAccessForm(
        request.POST or None,
        # Renewal: same username by default (to clear for a generated one).
        initial={
            "username": current.username if current else "",
            "expires_on": wifi.default_expiry(),
        },
    )
    if request.method == "POST":
        tokens = request.session.get(WIFI_TOKENS_KEY, [])
        expected = [request.POST.get("token", ""), resident.pk, stay.pk]
        if expected not in tokens:
            messages.info(
                request,
                "Ce formulaire a déjà servi, ou la chambre a changé depuis. Vérifiez la fiche.",
            )
            return redirect("residents:detail", pk=resident.pk)
        if form.is_valid():
            request.session[WIFI_TOKENS_KEY] = [t for t in tokens if t != expected]
            # The access the person saw on the form: if another one was recorded
            # since (double click, two people), nothing is recorded.
            seen = request.POST.get("replaces", "")
            replaces = stay.room.wifi_accesses.filter(pk=seen).first() if seen.isdigit() else None
            username = form.cleaned_data["username"]
            password = form.cleaned_data["password"]
            username_generated, generated = not username, not password
            if username_generated:
                username = wifi.generate_username()
            if generated:
                password = wifi.generate_password()
            try:
                access = wifi.set_access(
                    stay.room,
                    username=username,
                    password=password,
                    expires_on=form.cleaned_data["expires_on"],
                    stay=stay,
                    replaces=replaces,
                    generated=generated,
                    by=request.user,
                    request=request,
                )
            except ValidationError as error:
                messages.warning(request, error.messages[0])
                return redirect("residents:detail", pk=resident.pk)
            except ImproperlyConfigured:
                logger.exception("Wifi encryption is not configured")
                messages.warning(request, WIFI_NOT_CONFIGURED)
                return redirect("residents:detail", pk=resident.pk)
            if not (generated or username_generated):
                messages.success(
                    request,
                    f"L'accès wifi de la chambre {stay.room.number} est enregistré, valable "
                    f"jusqu'au {access.expires_on:%d/%m/%Y}.",
                )
                return redirect("residents:detail", pk=resident.pk)
            # Shown once, never cached: the person copies it on the network.
            return _never_cached(
                render(
                    request,
                    "residents/wifi_generated.html",
                    {
                        "active_nav": "residents",
                        "resident": resident,
                        "access": access,
                        "password": password,
                        "username_generated": username_generated,
                        "password_generated": generated,
                    },
                )
            )
    return _never_cached(
        render(
            request,
            "residents/wifi_access.html",
            {
                "active_nav": "residents",
                "resident": resident,
                "stay": stay,
                "current": current,
                "form": form,
                "token": _wifi_token(request, resident, stay),
                "wifi_settings": WifiSettings.load(),
            },
        )
    )


@sensitive_variables("password")
@login_required
@permission_required("accounts.view_wifi_password", raise_exception=True)
@recent_confirmation_required
def wifi_password(request, pk):
    """Show the stored password: administrators only, each display goes to the audit log."""
    resident, stay = _resident_room(request, pk)
    if stay is None:
        return redirect("residents:detail", pk=resident.pk)
    access = wifi.current_access(stay.room)
    if access is None:
        messages.info(request, "Cette chambre n'a pas d'accès wifi actif.")
        return redirect("residents:detail", pk=resident.pk)
    password = None
    if request.method == "POST":
        try:
            password = wifi.reveal_password(access, by=request.user, request=request)
        except WifiDecryptionError:
            logger.exception("Wifi password of room %s cannot be decrypted", stay.room.number)
            messages.warning(
                request,
                "Ce mot de passe ne peut pas être déchiffré avec les clés actuelles. "
                "Enregistrez un nouvel accès.",
            )
            return redirect("residents:detail", pk=resident.pk)
        except ImproperlyConfigured:
            logger.exception("Wifi encryption is not configured")
            messages.warning(request, WIFI_NOT_CONFIGURED)
            return redirect("residents:detail", pk=resident.pk)
    return _never_cached(
        render(
            request,
            "residents/wifi_password.html",
            {
                "active_nav": "residents",
                "resident": resident,
                "access": access,
                "password": password,
            },
        )
    )


# --- CSV and Excel import (card T08) ------------------------------------------

IMPORT_SESSION_KEY = "resident_import"
PREVIEW_DURATION = 60 * 60  # seconds
# Column titles of the template file: they stay in French, users type them.
TEMPLATE_HEADERS = ["Prénom", "Nom", "Téléphone", "Chambre", "Arrivée", "E-mail"]


@login_required
@permission_required("accounts.manage_residents", raise_exception=True)
def import_file(request):
    """Step 1: upload the file. It is read, then forgotten: only the analyzed rows
    stay in the session, one hour at most, until the confirmation."""
    form = ImportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        file = form.cleaned_data["file"]
        try:
            content = read_file(file)
            rows = analyze(content)
        except FileError as error:
            form.add_error("file", str(error))
        else:
            request.session[IMPORT_SESSION_KEY] = {
                # Ties the confirmation to this exact preview (two tabs, double click).
                "token": secrets.token_urlsafe(32),
                "created_at": time.time(),
                "file_name": file.name[:100],
                "rows": to_session(rows),
                # Its passwords are not kept: only the fact that they are there.
                "wifi": has_wifi_columns(content[0][1]),
            }
            return redirect("residents:import_preview")
    return render(
        request,
        "residents/import.html",
        {"active_nav": "residents", "form": form, "headers": HEADERS},
    )


def _pending_import(request):
    data = request.session.get(IMPORT_SESSION_KEY)
    if data and time.time() - data.get("created_at", 0) > PREVIEW_DURATION:
        # Names and numbers do not stay in the session longer than needed.
        del request.session[IMPORT_SESSION_KEY]
        messages.info(request, "L'aperçu a expiré. Envoyez de nouveau le fichier.")
        return None
    return data


def _confirm(request, pending_import, rows):
    """Create the residents. Return the created list, or None with an error message."""
    try:
        with transaction.atomic():
            record = ResidentImport.objects.create(
                token=pending_import["token"],
                imported_by=request.user,
                file_name=pending_import["file_name"],
            )
            created = run_import(rows)
            record.count = len(created)
            record.save(update_fields=["count"])
    except ValidationError as error:
        messages.warning(request, f"Rien n'a été importé. {' '.join(error.messages)}")
    except IntegrityError:
        if ResidentImport.objects.filter(token=pending_import["token"]).exists():
            messages.info(request, "Cet import a déjà été fait.")
            del request.session[IMPORT_SESSION_KEY]
            return []
        messages.warning(
            request,
            "Rien n'a été importé : une chambre ou un numéro vient d'être pris. "
            "Vérifiez l'aperçu à jour.",
        )
    else:
        return created
    return None


MAX_SMS_CODES = 20  # above this, the page would wait too long for the providers


def _send_codes(request, residents):
    """Import option: an activation code by SMS to the new residents who have a number."""
    address = request.build_absolute_uri(reverse("activation:enter_code"))
    with_number = [r for r in residents if r.phone]
    if len(with_number) > MAX_SMS_CODES:
        messages.warning(
            request,
            f"Plus de {MAX_SMS_CODES} codes à envoyer : aucun SMS n'est parti. "
            "Remettez les codes à l'accueil, ou envoyez-les depuis chaque fiche.",
        )
        return
    sent = 0
    for resident in with_number:
        try:
            sent += send_code_by_sms(resident, address, by=request.user, request=request)
        except Exception:  # an unexpected failure must not hide the successful import
            logger.exception("Could not send the activation code")
    if sent:
        s = "s" if sent > 1 else ""
        messages.success(request, f"{sent} code{s} d'activation envoyé{s} par SMS.")
    if sent < len(with_number):
        messages.warning(
            request,
            f"{len(with_number) - sent} SMS n'ont pas pu partir. "
            "Donnez un nouveau code depuis la fiche de chaque résident.",
        )
    if len(with_number) < len(residents):
        messages.info(
            request,
            f"{len(residents) - len(with_number)} résident(s) sans numéro : "
            "code à remettre à l'accueil.",
        )


@login_required
@permission_required("accounts.manage_residents", raise_exception=True)
def import_preview(request):
    """Step 2: row by row preview, then import of the ready rows."""
    pending_import = _pending_import(request)
    if not pending_import:
        return redirect("residents:import")
    rows = from_session(pending_import["rows"])
    ready = [row.number for row in rows if row.ready]
    state_changed = other_preview = False

    if request.method == "POST":
        if request.POST.get("token") != pending_import["token"]:
            # This tab showed another file, replaced since then in the session.
            other_preview = True
        elif request.POST.get("action") == "cancel":
            del request.session[IMPORT_SESSION_KEY]
            messages.info(request, "Import annulé. Aucune fiche n'a été créée.")
            return redirect("residents:import")
        elif request.POST.get("ready", "") != ",".join(map(str, ready)):
            # A room or a number was taken since the preview.
            state_changed = True
        else:
            created = _confirm(request, pending_import, rows)
            if created is not None:
                request.session.pop(IMPORT_SESSION_KEY, None)
                if created:
                    s = "s" if len(created) > 1 else ""
                    messages.success(request, f"{len(created)} résident{s} importé{s}.")
                    can_issue = request.user.has_perm("accounts.issue_activation_codes")
                    if request.POST.get("send_codes") == "yes" and can_issue:
                        _send_codes(request, created)
                    if pending_import.get("wifi"):
                        messages.info(
                            request,
                            "Ce fichier contient aussi les accès wifi : envoyez-le maintenant "
                            "dans «\u00a0Importer la liste wifi\u00a0».",
                        )
                return redirect("residents:list")
            rows = from_session(pending_import["rows"])
            ready = [row.number for row in rows if row.ready]

    return render(
        request,
        "residents/import.html",
        {
            "active_nav": "residents",
            "file_name": pending_import["file_name"],
            "token": pending_import["token"],
            "rows": rows,
            "ready": ",".join(map(str, ready)),
            "ready_count": len(ready),
            "to_fix_count": len(rows) - len(ready),
            "state_changed": state_changed,
            "other_preview": other_preview,
        },
    )


@require_GET
@login_required
@permission_required("accounts.manage_residents", raise_exception=True)
def import_template(request):
    """Template file: the column titles, as a CSV that Excel can read (BOM and ";")."""
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="modele-import-residents.csv"'
    response.write("﻿" + ";".join(TEMPLATE_HEADERS) + "\r\n")
    return response
