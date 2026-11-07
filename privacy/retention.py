"""How long personal data is kept, and its deletion (card T36, GDPR).

The association, as data controller, sets the durations. The
administration changes them on the page "Réglages" (residence app, card
T37b, within safe bounds), so that the page "Vos données" and the purge
use the same ones; docs/registre-des-traitements.md lists
them too. `manage.py purge_personal_data` counts what is past its time;
with --apply it deletes it. Run it once a day, after the durations are
validated.

What goes, and when (default durations):
- a former resident (account disabled, at least one stay, none in
  progress): the account and all that is linked to it, 365 days after the
  last departure. That is stays, deliveries and answers, meetings, direct
  messages, passkeys, notification subscriptions, codes. Their reports
  stay for the room's repair history, with nothing of the person: no
  name, no text, no note, no photo (reports/service.py, forget_resident);
- the photos of a closed report: 180 days after it was closed;
- meetings (with their reason) and direct messages: 365 days after; a
  conversation left empty goes too;
- who received a message, who was chosen or left out by name, and the
  answers "Présent ou Absent": 365 days after the sending (the message
  itself stays, without its recipients);
- ended wifi accesses of a room: 365 days after they ended (or expired,
  when switched off with no end time);
- the audit log: 365 days (the CNIL recommends 6 months to 1 year);
- activation codes, failed tries, phone checks: 30 days.
Votes are anonymous: only totals and "who voted, which day" exist, and the
second goes with the account.
"""

from dataclasses import dataclass, fields
from datetime import timedelta

from django.db import transaction
from django.db.models import Exists, Max, OuterRef, ProtectedError, Q
from django.utils import timezone

# The kinds of data with a retention duration (ResidenceSettings.<kind>_days).
KINDS = (
    "former_residents",
    "report_photos",
    "meetings",
    "direct_messages",
    "deliveries",
    "wifi_accesses",
    "audit_log",
    "codes",
)

# For the audit log: "3 anciens résidents, 12 photos..."
LABELS = {
    "former_residents": ("ancien résident", "anciens résidents"),
    "report_photos": ("photo de signalement", "photos de signalement"),
    "meetings": ("rendez-vous", "rendez-vous"),
    "direct_messages": ("message direct", "messages directs"),
    "conversations": ("conversation vide", "conversations vides"),
    "deliveries": ("envoi à un résident", "envois à un résident"),
    "attendance_replies": ("réponse à une visite", "réponses à une visite"),
    "wifi_accesses": ("ancien accès wifi", "anciens accès wifi"),
    "audit_entries": ("entrée du journal", "entrées du journal"),
    "codes": ("code ou essai", "codes ou essais"),
    "kept": ("ancien compte gardé, encore lié", "anciens comptes gardés, encore liés"),
}


def days(key):
    """Days a kind of data is kept (residence settings, card T37b)."""
    from residence.models import ResidenceSettings

    return ResidenceSettings.load().retention_days(key)


@dataclass
class Purge:
    """What was (or would be) deleted, by kind."""

    former_residents: int = 0
    report_photos: int = 0
    meetings: int = 0
    direct_messages: int = 0
    conversations: int = 0
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
    """Residents gone for good: account disabled, at least one stay, none in
    progress, last departure older than the limit.

    An account that never had a stay is never chosen: nothing says when it
    stopped being used (it may also be a former staff member whose roles
    were removed). The staff deletes it by hand if needed.
    """
    from accounts.models import User
    from housing.models import Stay

    limit = timezone.localtime(now).date() - timedelta(days=days("former_residents"))
    return (
        User.objects.residents()
        .filter(is_active=False)
        .filter(Exists(Stay.objects.filter(resident=OuterRef("pk"))))
        .exclude(Exists(_housed()))
        .annotate(last_departure=Max("stays__departure"))
        .filter(last_departure__lte=limit)
    )


def _queries(now):
    from accounts.models import ActivationCode, ActivationFailure, PhoneVerification
    from appointments.models import Appointment, Conversation, DirectMessage
    from audit.models import AuditEntry
    from housing.models import WifiAccess
    from messaging.models import AttendanceReply, Delivery
    from reports.models import Report, ReportPhoto

    def before(key):
        return now - timedelta(days=days(key))

    wifi_day = timezone.localtime(before("wifi_accesses")).date()
    return {
        "report_photos": [
            ReportPhoto.objects.filter(
                report__status=Report.Status.CLOSED, report__updated_at__lte=before("report_photos")
            )
        ],
        "meetings": [Appointment.objects.filter(end__lte=before("meetings"))],
        "direct_messages": [DirectMessage.objects.filter(sent_at__lte=before("direct_messages"))],
        # Once its messages are gone, a conversation still says who talked
        # to whom, and when.
        "conversations": [
            Conversation.objects.filter(updated_at__lte=before("direct_messages")).exclude(
                Exists(
                    DirectMessage.objects.filter(
                        conversation=OuterRef("pk"), sent_at__gt=before("direct_messages")
                    )
                )
            )
        ],
        "deliveries": [Delivery.objects.filter(campaign__started_at__lte=before("deliveries"))],
        "attendance_replies": [
            AttendanceReply.objects.filter(campaign__started_at__lte=before("deliveries"))
        ],
        # Switched off in the admin site, an access may have no end time:
        # its expiry date counts then.
        "wifi_accesses": [
            WifiAccess.objects.filter(active=False).filter(
                Q(ended_at__lte=before("wifi_accesses"))
                | Q(ended_at__isnull=True, expires_on__lte=wifi_day)
            )
        ],
        "audit_entries": [AuditEntry.objects.filter(created_at__lte=before("audit_log"))],
        "codes": [
            ActivationCode.objects.filter(expires_at__lte=before("codes")),
            ActivationFailure.objects.filter(created_at__lte=before("codes")),
            PhoneVerification.objects.filter(created_at__lte=before("codes")),
        ],
    }


def _photos_of(people):
    """The photos of the reports of these people: they go with the account."""
    from reports.models import ReportPhoto

    return ReportPhoto.objects.filter(report__resident__in=people.values("pk"))


def _targets(now):
    """The people chosen or left out by name in a message: who was aimed at.
    Cleared with the deliveries; the message itself stays."""
    from messaging.models import Campaign

    limit = now - timedelta(days=days("deliveries"))
    return [
        through.objects.filter(campaign__started_at__lte=limit)
        for through in (Campaign.people.through, Campaign.excluded.through)
    ]


def _lock_former(candidates):
    """Lock the candidates and check them again: someone who came back
    between the count and the deletion stays."""
    from accounts.models import User

    return list(
        User.objects.select_for_update()
        .filter(pk__in=candidates, is_active=False)
        .exclude(Exists(_housed()))
        .values_list("pk", flat=True)
    )


def run(apply=False, now=None):
    """Count, and with ``apply`` delete, what is past its time. Return a Purge.

    One transaction. A former resident goes in a savepoint of their own:
    if something still protects the account, it stays and the rest goes on.
    The files of the deleted photos go after the commit (reports/signals.py).
    The audit log then gets one entry with what was really deleted, never
    what it held.
    """
    now = now or timezone.now()
    people = former_residents(now)
    queries = _queries(now)
    counted = Purge(
        former_residents=people.count(),
        **{key: sum(q.count() for q in found) for key, found in queries.items()},
    )
    counted.report_photos += _photos_of(people).exclude(pk__in=queries["report_photos"][0]).count()
    if not apply or not counted.total():
        return counted
    from accounts.models import User
    from audit.models import Action
    from audit.service import log_action
    from housing.models import Stay
    from reports.service import forget_resident

    done = Purge()
    kept = 0
    with transaction.atomic():
        candidates = list(people.values_list("pk", flat=True))
        for pk in _lock_former(candidates):
            try:
                with transaction.atomic():
                    # Their reports stay for the room's repair history,
                    # with nothing of the person (reports/service.py).
                    photos = forget_resident(pk, now)
                    # Stays protect their resident (room history): first.
                    Stay.objects.filter(resident_id=pk).delete()
                    User.objects.filter(pk=pk).delete()
            except ProtectedError:
                kept += 1
            else:
                done.former_residents += 1
                done.report_photos += photos
        # A queryset delete sends post_delete for each photo (its file goes)
        # and never calls AuditEntry.delete, which refuses a single entry.
        for key, found in queries.items():
            for query in found:
                _, by_model = query.delete()
                setattr(done, key, getattr(done, key) + by_model.get(query.model._meta.label, 0))
        for query in _targets(now):
            query.delete()
        details = {key: value for key, value in done.counts().items() if value}
        if kept:
            details["kept"] = kept
        if details:
            log_action(Action.DATA_PURGED, details=details)
    return done
