"""Import of the existing wifi list, staff side (card T15b).

Reserved to the people who can show a wifi password (Administration), after a
recent passkey confirmation: the file holds every password of the residence.
"""

import logging
import secrets
import time

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils.cache import add_never_cache_headers
from django.views.decorators.http import require_GET

from access.decorators import recent_confirmation_required
from housing.wifi_crypto import WifiDecryptionError

from .bulk_import import FileError, read_file
from .forms import ImportForm
from .views import WIFI_NOT_CONFIGURED
from .wifi_import import TEMPLATE_HEADERS, analyze, from_session, run_import, to_session

logger = logging.getLogger(__name__)

SESSION_KEY = "wifi_import"
# The file holds every password: front desk rights plus the right to show a password.
PERMISSIONS = ("accounts.manage_residents", "accounts.view_wifi_password")
PREVIEW_DURATION = 30 * 60  # seconds: the passwords do not stay longer, even encrypted


def _page(request, context):
    response = render(request, "residents/wifi_import.html", {"active_nav": "residents", **context})
    add_never_cache_headers(response)
    return response


def _pending(request):
    data = request.session.get(SESSION_KEY)
    if data and time.time() - data.get("created_at", 0) > PREVIEW_DURATION:
        del request.session[SESSION_KEY]
        messages.info(request, "L'aperçu a expiré. Envoyez de nouveau le fichier.")
        return None
    return data


@login_required
@permission_required(PERMISSIONS, raise_exception=True)
@recent_confirmation_required
def wifi_import_file(request):
    """Step 1: upload the file. Only the analyzed rows stay in the session."""
    form = ImportForm(request.POST or None, request.FILES or None)
    form.fields["file"].help_text = "Format .csv ou .xlsx, 2 Mo au plus, 500 lignes au plus."
    if request.method == "POST" and form.is_valid():
        file = form.cleaned_data["file"]
        try:
            rows = analyze(read_file(file))
        except FileError as error:
            form.add_error("file", str(error))
        except ImproperlyConfigured:
            logger.exception("Wifi encryption keys missing")
            form.add_error("file", WIFI_NOT_CONFIGURED)
        else:
            request.session[SESSION_KEY] = {
                # Ties the confirmation to this exact preview (two tabs, double click).
                "token": secrets.token_urlsafe(32),
                "created_at": time.time(),
                "file_name": file.name[:100],
                "rows": to_session(rows),
            }
            return redirect("residents:wifi_import_preview")
    return _page(request, {"form": form})


@login_required
@permission_required(PERMISSIONS, raise_exception=True)
@recent_confirmation_required
def wifi_import_preview(request):
    """Step 2: row by row preview, then recording of the ready rows."""
    pending = _pending(request)
    if not pending:
        return redirect("residents:wifi_import")
    rows = from_session(pending["rows"])
    state = ",".join(row.state for row in rows if row.ready)
    state_changed = other_preview = False

    if request.method == "POST":
        if request.POST.get("token") != pending["token"]:
            other_preview = True  # this tab showed another file, replaced since then
        elif request.POST.get("action") == "cancel":
            del request.session[SESSION_KEY]
            messages.info(request, "Import annulé. Aucun accès wifi n'a été enregistré.")
            return redirect("residents:wifi_import")
        elif request.POST.get("state", "") != state:
            state_changed = True  # a departure or another recording since the preview
        else:
            # The preview is used once, whatever happens next.
            del request.session[SESSION_KEY]
            try:
                count = run_import(rows, by=request.user, request=request)
            except ValidationError as error:
                if error.code == "access_changed":
                    # Often a second click: the first one may have recorded everything.
                    messages.warning(
                        request,
                        "Rien n'a été enregistré par cet envoi : un accès a changé entre-temps, "
                        "peut-être par un premier clic. Vérifiez la liste des résidents avant "
                        "d'envoyer de nouveau le fichier.",
                    )
                    return redirect("residents:list")
                messages.warning(
                    request,
                    f"Rien n'a été enregistré. {' '.join(error.messages)} "
                    "Envoyez de nouveau le fichier.",
                )
                return redirect("residents:wifi_import")
            except (ImproperlyConfigured, WifiDecryptionError):
                logger.exception("Wifi import failed")
                messages.warning(request, WIFI_NOT_CONFIGURED)
                return redirect("residents:wifi_import")
            s = "s" if count > 1 else ""
            messages.success(request, f"{count} accès wifi enregistré{s}.")
            return redirect("residents:list")

    ready_count = sum(row.ready for row in rows)
    unchanged_count = sum(row.unchanged for row in rows)
    return _page(
        request,
        {
            "file_name": pending["file_name"],
            "token": pending["token"],
            "rows": rows,
            "state": state,
            "ready_count": ready_count,
            "unchanged_count": unchanged_count,
            "to_fix_count": len(rows) - ready_count - unchanged_count,
            "state_changed": state_changed,
            "other_preview": other_preview,
        },
    )


@require_GET
@login_required
@permission_required(PERMISSIONS, raise_exception=True)
def wifi_import_template(request):
    """Template file: the column titles, as a CSV that Excel can read (BOM and ";")."""
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="modele-import-wifi.csv"'
    response.write("﻿" + ";".join(TEMPLATE_HEADERS) + "\r\n")
    return response
