"""The page "Réglages" of the residence (card T37b): administration only."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache

from access.decorators import recent_confirmation_required
from audit.models import Action
from audit.service import log_action

from .forms import ResidenceSettingsForm
from .models import ResidenceSettings


@never_cache
@login_required
@permission_required("accounts.manage_settings", raise_exception=True)
@recent_confirmation_required
def edit(request):
    from sms.service import (
        active_provider,
        configured_provider,
        daily_limit,
        ready_providers,
        sent_today,
    )

    with transaction.atomic():
        current = ResidenceSettings.objects.select_for_update().get(pk=ResidenceSettings.load().pk)
        form = ResidenceSettingsForm(request.POST or None, instance=current)
        if request.method == "POST" and form.is_valid():
            changes = form.changes()
            if changes:
                form.save()
                log_action(
                    Action.SETTINGS_CHANGED,
                    actor=request.user,
                    target=current,
                    details={"changed": changes},
                    request=request,
                )
                messages.success(request, "Les réglages sont enregistrés.")
            else:
                messages.info(request, "Rien n'a changé.")
            return redirect("residence:edit")
    return render(
        request,
        "residence/edit.html",
        {
            "active_nav": "settings",
            "form": form,
            "server_sms": configured_provider().name,
            "active_sms": active_provider().name,
            "sms_today": sent_today(),
            "sms_limit": daily_limit(),
            "paused": current.sms_provider == "paused",
            # A chosen service whose keys went: the server's one sends instead.
            "fallback": current.sms_provider not in ("", "paused")
            and current.sms_provider not in ready_providers(),
        },
    )
