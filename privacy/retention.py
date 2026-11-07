"""How long personal data is kept, and its deletion (card T36, GDPR).

The association, as data controller, sets the durations. They are settings
(RETENTION_DAYS in config/settings/base.py) so that the page "Vos données"
and the purge use the same ones; docs/registre-des-traitements.md lists
them too. `manage.py purge_personal_data` counts what is past its time;
with --apply it deletes it. Run it once a day, after the durations are
validated.

What goes, and when (default durations):
- a former resident (account disabled, no stay in progress): the account
  and all that is linked to it, 365 days after the last departure. That is
  stays, deliveries and answers, meetings, direct messages, reports and
  their photos, passkeys, notification subscriptions, codes;
- the photos of a closed report: 180 days after it was closed;
- meetings (with their reason) and direct messages: 365 days after;
- who received a message, and their answer "Présent ou Absent": 365 days
  after the sending (the message itself stays, without its recipients);
- ended wifi accesses of a room: 365 days after they ended;
- the audit log: 365 days (the CNIL recommends 6 months to 1 year);
- activation codes, failed tries, phone checks: 30 days.
Votes are anonymous: only totals and "who voted, which day" exist, and the
second goes with the account.
"""

from dataclasses import dataclass, fields
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Exists, Max, OuterRef, Q
from django.utils import timezone

DEFAULTS = {
    "former_residents": 365,
    "report_photos": 180,
    "meetings": 365,
    "direct_messages": 365,
    "deliveries": 365,
    "wifi_accesses": 365,
    "audit_log": 365,
    "codes": 30,
}

# For the audit log: "3 anciens résidents, 12 photos..."
LABELS = {
    "former_residents": ("ancien résident", "anciens résidents"),
    "report_photos": ("photo de signalement", "photos de signalement"),
    "meetings": ("rendez-vous", "rendez-vous"),
    "direct_messages": ("message direct", "messages directs"),
    "deliveries": ("envoi à un résident", "envois à un résident"),
    "attendance_replies": ("réponse à une visite", "réponses à une visite"),
    "wifi_accesses": ("ancien accès wifi", "anciens accès wifi"),
    "audit_entries": ("entrée du journal", "entrées du journal"),
    "codes": ("code ou essai", "codes ou essais"),
}


def days(key):
    """Days a kind of data is kept: the setting, or the default."""
    return int(getattr(settings, "RETENTION_DAYS", {}).get(key, DEFAULTS[key]))


@dataclass
class Purge:
    """What was (or would be) deleted, by kind."""

    former_residents: int = 0
    report_photos: int = 0
    meetings: int = 0
    direct_messages: int = 0
    deliveries: int = 0
    attendance_replies: int = 0
    wifi_accesses: int = 0
    audit_entries: int = 0
    codes: int = 0

    def counts(self):
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def total(self):
        return sum(self.counts().values())


def describe(counts):
    """French words for the counts, without the zeros."""
    parts = []
    for key, (one, many) in LABELS.items():
        number = counts.get(key, 0)
        if number:
            parts.append(f"{number} {one if number == 1 else many}")
    return ", ".join(parts)


def _housed():
    from housing.models import Stay

    return Stay.objects.filter(resident=OuterRef("pk"), departure__isnull=True)


def former_residents(now):
    """Residents gone for good: account disabled, no stay in progress, last
    departure older than the limit (or no stay at all, and an account older
    than the limit). A staff account is never one of them."""
    from accounts.models import User

    keep = days("former_residents")
    limit = timezone.localtime(now).date() - timedelta(days=keep)
    return (
        User.objects.residents()
        .filter(is_active=False)
        .exclude(Exists(_housed()))
        .annotate(last_departure=Max("stays__departure"))
        .filter(
            Q(last_departure__lte=limit)
            | Q(last_departure__isnull=True, date_joined__lte=now - timedelta(days=keep))
        )
    )


def _queries(now):
    from accounts.models import ActivationCode, ActivationFailure, PhoneVerification
    from appointments.models import Appointment, DirectMessage
    from audit.models import AuditEntry
    from housing.models import WifiAccess
    from messaging.models import AttendanceReply, Delivery
    from reports.models import Report, ReportPhoto

    def before(key):
        return now - timedelta(days=days(key))

    return {
        "report_photos": [
            ReportPhoto.objects.filter(
                report__status=Report.Status.CLOSED, report__updated_at__lte=before("report_photos")
            )
        ],
        "meetings": [Appointment.objects.filter(end__lte=before("meetings"))],
        "direct_messages": [DirectMessage.objects.filter(sent_at__lte=before("direct_messages"))],
        "deliveries": [Delivery.objects.filter(campaign__started_at__lte=before("deliveries"))],
        "attendance_replies": [
            AttendanceReply.objects.filter(campaign__started_at__lte=before("deliveries"))
        ],
        "wifi_accesses": [
            WifiAccess.objects.filter(active=False, ended_at__lte=before("wifi_accesses"))
        ],
        "audit_entries": [AuditEntry.objects.filter(created_at__lte=before("audit_log"))],
        "codes": [
            ActivationCode.objects.filter(expires_at__lte=before("codes")),
            ActivationFailure.objects.filter(created_at__lte=before("codes")),
            PhoneVerification.objects.filter(created_at__lte=before("codes")),
        ],
    }


def run(apply=False, now=None):
    """Count, and with ``apply`` delete, what is past its time. Return a Purge.

    All or nothing: one transaction. The files of the deleted photos go
    after the commit (reports/signals.py). The audit log then gets one
    entry with the counts, never what was deleted.
    """
    now = now or timezone.now()
    people = former_residents(now)
    queries = _queries(now)
    result = Purge(
        former_residents=people.count(),
        **{key: sum(q.count() for q in found) for key, found in queries.items()},
    )
    if not apply or not result.total():
        return result
    from audit.models import Action
    from audit.service import log_action
    from housing.models import Stay

    with transaction.atomic():
        # A queryset delete sends post_delete for each photo (its file goes)
        # and never calls AuditEntry.delete, which refuses a single entry.
        for found in queries.values():
            for query in found:
                query.delete()
        # Locked, then checked again: someone who came back meanwhile stays.
        gone = list(
            people.model.objects.select_for_update()
            .filter(pk__in=list(people.values_list("pk", flat=True)), is_active=False)
            .exclude(Exists(_housed()))
            .values_list("pk", flat=True)
        )
        # Stays protect their resident (room history): they go first.
        Stay.objects.filter(resident__in=gone).delete()
        people.model.objects.filter(pk__in=gone).delete()
        log_action(
            Action.DATA_PURGED,
            details={key: value for key, value in result.counts().items() if value},
        )
    return result
