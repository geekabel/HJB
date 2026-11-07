from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone
from django.utils.formats import date_format


class Action(models.TextChoices):
    ROLES_CHANGED = "roles_changed", "Rôles modifiés"
    ACTIVATION_CODE_ISSUED = "activation_code_issued", "Code d'activation généré"
    WIFI_PASSWORD_SHOWN = "wifi_password_shown", "Mot de passe wifi affiché"
    RESIDENT_DEPARTED = "resident_departed", "Départ d'un résident"
    RESIDENT_RETURNED = "resident_returned", "Retour d'un ancien résident"
    PASSKEY_CREATED = "passkey_created", "Clé d'accès créée"
    APP_CODE_CREATED = "app_code_created", "Application de codes reliée"
    APP_CODE_FAILURES = "app_code_failures", "Codes d'application faux à répétition"
    ACCESS_CUT = "access_cut", "Accès coupé (téléphone perdu)"
    WIFI_ACCESS_SET = "wifi_access_set", "Accès wifi enregistré"
    MESSAGE_SCHEDULED = "message_scheduled", "Message programmé"
    MESSAGE_CANCELLED = "message_cancelled", "Envoi d'un message annulé"
    MESSAGE_SENT = "message_sent", "Message envoyé"
    DEPARTURE_PLANNED = "departure_planned", "Départ prévu"
    DEPARTURE_PLAN_CANCELLED = "departure_plan_cancelled", "Départ prévu annulé"
    DATA_PURGED = "data_purged", "Données anciennes supprimées"


class AuditEntryImmutable(Exception):
    """An audit entry is never changed, and never deleted one by one."""


class AuditEntry(models.Model):
    """A sensitive action: who, what, on what, when, from which address.

    The entry keeps readable labels (actor, target) so it stays
    understandable even if the account or the object is deleted.
    Generic relation: Django docs "The contenttypes framework".
    """

    created_at = models.DateTimeField("date", default=timezone.now, db_index=True, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="acteur",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_entries",
    )
    actor_label = models.CharField("acteur (au moment de l'action)", max_length=150, blank=True)
    action = models.CharField(max_length=40, choices=Action.choices, db_index=True)
    # An audit log must not disappear with an object type: PROTECT.
    target_type = models.ForeignKey(
        ContentType, null=True, blank=True, on_delete=models.PROTECT, verbose_name="type de cible"
    )
    # Text: works with any primary key (contenttypes docs).
    target_id = models.CharField("identifiant de la cible", max_length=64, blank=True)
    target = GenericForeignKey("target_type", "target_id")
    target_label = models.CharField("cible (au moment de l'action)", max_length=200, blank=True)
    details = models.JSONField("détails", default=dict, blank=True)
    ip_address = models.GenericIPAddressField("adresse IP", null=True, blank=True)

    class Meta:
        verbose_name = "entrée du journal"
        verbose_name_plural = "journal d'audit"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["target_type", "target_id"])]

    def __str__(self):
        return (
            f"{self.created_at:%d/%m/%Y %H:%M} · {self.get_action_display()} · {self.target_label}"
        )

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AuditEntryImmutable("An audit entry cannot be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AuditEntryImmutable(
            "An audit entry cannot be deleted one by one. "
            "Old entries go with the retention purge (privacy/retention.py)."
        )

    def summary(self):
        """Details in plain words, for the audit log page; a dash when there are none.

        Never fails: an old entry with missing details shows the dash.
        """
        try:
            text = self._summary()
        except (KeyError, ValueError, TypeError):
            text = ""
        text = text.strip()
        return text if text and text != "." else NO_DETAILS

    def _summary(self):
        if self.action == Action.ROLES_CHANGED:
            from accounts.roles import Role

            def labels(codes):
                return ", ".join(Role(c).label for c in codes) or "aucun (résident)"

            return (
                f"Avant : {labels(self.details.get('before', []))}. "
                f"Après : {labels(self.details.get('after', []))}."
            )
        if self.action == Action.RESIDENT_RETURNED:
            from datetime import date

            day = date.fromisoformat(self.details["arrival"])
            return (
                f"Chambre {self.details.get('room', '?')}, retour le {date_format(day, 'j F Y')}."
            )
        if self.action == Action.ACTIVATION_CODE_ISSUED and "expires_at" in self.details:
            from datetime import datetime

            from django.utils import timezone

            end = timezone.localtime(datetime.fromisoformat(self.details["expires_at"]))
            text = f"Valable jusqu'au {date_format(end, 'j F Y à H:i')}."
            return f"Code du personnel. {text}" if self.details.get("staff") else text
        if self.action == Action.RESIDENT_DEPARTED:
            from datetime import date

            parts = []
            if self.details.get("room"):
                parts.append(f"Chambre {self.details['room']}")
            if self.details.get("departure"):
                day = date.fromisoformat(self.details["departure"])
                parts.append(f"départ le {date_format(day, 'j F Y')}")
            sessions = self.details.get("sessions_closed", 0)
            text = ", ".join(parts)
            text = text[:1].upper() + text[1:] + "."
            if sessions:
                s = "s" if sessions > 1 else ""
                text += f" {sessions} session{s} fermée{s}."
            passkeys = self.details.get("passkeys_removed", 0)
            if passkeys:
                s = "s" if passkeys > 1 else ""
                text += f" {passkeys} clé{s} d'accès supprimée{s}."
            if self.details.get("wifi_cut"):
                text += " Accès wifi coupé."
            return text.strip()
        if self.action == Action.WIFI_ACCESS_SET:
            from datetime import date

            end = date.fromisoformat(self.details["expires_on"])
            room = self.details.get("room", "?")
            text = f"Chambre {room}, valable jusqu'au {date_format(end, 'j F Y')}."
            return text + (" Mot de passe généré." if self.details.get("generated") else "")
        if self.action == Action.WIFI_PASSWORD_SHOWN and "room" in self.details:
            return f"Chambre {self.details['room']}."
        if self.action == Action.ACCESS_CUT:
            passkeys = self.details.get("passkeys_removed", 0)
            sessions = self.details.get("sessions_closed", 0)
            sp, ss = ("s" if passkeys > 1 else ""), ("s" if sessions > 1 else "")
            return f"{passkeys} clé{sp} d'accès supprimée{sp}, {sessions} session{ss} fermée{ss}."
        if self.action == Action.PASSKEY_CREATED:
            previous = self.details.get("previous_removed", 0)
            if not previous:
                return "Première clé d'accès."
            s = "s" if previous > 1 else ""
            return f"Remplace {previous} ancienne{s} clé{s}, désormais inutilisable{s}."
        if self.action in (Action.MESSAGE_SENT, Action.MESSAGE_SCHEDULED):
            return _message_summary(self.details)
        if self.action == Action.MESSAGE_CANCELLED:
            if self.details.get("reason"):
                return self.details["reason"]
            if self.details.get("reminder_too_late"):
                return "Relance trop tardive : elle n'est pas partie."
            if self.details.get("reminder"):
                return "Relance annulée."
            if self.details.get("too_late"):
                return "Trop tard pour l'envoyer : rien n'est parti."
            return "Remis en brouillon." if self.details.get("back_to_draft") else "Envoi annulé."
        if self.action in (Action.DEPARTURE_PLANNED, Action.DEPARTURE_PLAN_CANCELLED):
            from datetime import date

            parts = []
            if self.details.get("room"):
                parts.append(f"Chambre {self.details['room']}")
            if self.details.get("planned_departure"):
                day = date.fromisoformat(self.details["planned_departure"])
                parts.append(f"départ prévu le {date_format(day, 'j F Y')}")
            text = ", ".join(parts)
            text = (text[:1].upper() + text[1:] + ".") if text else ""
            if self.details.get("reason"):
                text += f" {self.details['reason']}"
            return text.strip()
        if self.action == Action.APP_CODE_CREATED:
            previous = self.details.get("previous_removed", 0)
            if not previous:
                return "Premier accès."
            return f"Remplace {previous} ancien{'s' if previous > 1 else ''} accès."
        if self.action == Action.DATA_PURGED:
            from privacy.retention import describe

            text = describe(self.details)
            return (text[:1].upper() + text[1:] + ".") if text else ""
        if self.action == Action.APP_CODE_FAILURES:
            failures = self.details.get("failures")
            return f"{failures} codes faux d'affilée." if failures else ""
        # Any other detail: never a raw key on the page.
        return " · ".join(
            f"{DETAIL_LABELS.get(key, key)} : {value}" for key, value in self.details.items()
        )


NO_DETAILS = "\u2013"  # an en dash, as in the empty cells of the other tables

DETAIL_LABELS = {
    "recipients": "destinataires",
    "push": "notifications",
    "sms": "SMS",
    "segments": "SMS facturés",
    "failed": "échecs",
    "room": "chambre",
    "reason": "raison",
}


def _message_summary(details):
    """ "6 destinataires, 5 notifications, 1 SMS (2 facturés), 1 échec." """
    from datetime import datetime

    def count(n, word, plural=None):
        # French: the singular for 0 and 1.
        return f"{n} {word if n <= 1 else (plural or word + 's')}"

    parts = []
    if "recipients" in details:
        parts.append(count(details["recipients"], "destinataire"))
    if "push" in details:
        parts.append(count(details["push"], "notification"))
    if "sms" in details:
        sms = count(details["sms"], "SMS", "SMS")
        if details.get("segments"):
            sms += f" ({count(details['segments'], 'facturé')})"
        parts.append(sms)
    if details.get("failed"):
        parts.append(count(details["failed"], "échec"))
    text = ", ".join(parts)
    if details.get("send_at"):
        when = datetime.fromisoformat(details["send_at"])
        text = f"Prévu le {date_format(when, 'j F Y à H:i')}. " + (text[:1].upper() + text[1:])
    elif text:
        text = text[:1].upper() + text[1:]
    if details.get("reminder"):
        text = "Relance. " + text
    return (text + ".") if text and not text.endswith(".") else text
