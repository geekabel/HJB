from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone


class Action(models.TextChoices):
    ROLES_CHANGED = "roles_changed", "Rôles modifiés"
    ACTIVATION_CODE_ISSUED = "activation_code_issued", "Code d'activation généré"
    WIFI_PASSWORD_SHOWN = "wifi_password_shown", "Mot de passe wifi affiché"
    RESIDENT_DEPARTED = "resident_departed", "Départ d'un résident"
    RESIDENT_RETURNED = "resident_returned", "Retour d'un ancien résident"
    PASSKEY_CREATED = "passkey_created", "Clé d'accès créée"
    ACCESS_CUT = "access_cut", "Accès coupé (téléphone perdu)"
    WIFI_ACCESS_SET = "wifi_access_set", "Accès wifi enregistré"
    MESSAGE_SCHEDULED = "message_scheduled", "Message programmé"
    MESSAGE_CANCELLED = "message_cancelled", "Envoi d'un message annulé"
    MESSAGE_SENT = "message_sent", "Message envoyé"
    DEPARTURE_PLANNED = "departure_planned", "Départ prévu"
    DEPARTURE_PLAN_CANCELLED = "departure_plan_cancelled", "Départ prévu annulé"


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
            "Purging by retention period is planned in T36."
        )

    def summary(self):
        """Details in plain words, for the audit log page."""
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
            return f"Chambre {self.details.get('room', '?')}, retour le {day:%d/%m/%Y}."
        if self.action == Action.ACTIVATION_CODE_ISSUED and "expires_at" in self.details:
            from datetime import datetime

            from django.utils import timezone

            end = timezone.localtime(datetime.fromisoformat(self.details["expires_at"]))
            text = f"Valable jusqu'au {end:%d/%m/%Y à %H:%M}."
            return f"Code du personnel. {text}" if self.details.get("staff") else text
        if self.action == Action.RESIDENT_DEPARTED:
            from datetime import date

            parts = []
            if self.details.get("room"):
                parts.append(f"Chambre {self.details['room']}")
            if self.details.get("departure"):
                day = date.fromisoformat(self.details["departure"])
                parts.append(f"départ le {day:%d/%m/%Y}")
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
            text = f"Chambre {self.details.get('room', '?')}, valable jusqu'au {end:%d/%m/%Y}."
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
        return " · ".join(f"{key} : {value}" for key, value in self.details.items())
