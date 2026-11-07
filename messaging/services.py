"""Composer actions (card T20): add a recipient, send a test to oneself."""

import logging
import unicodedata

from django.db.models import Q

from accounts.models import User
from housing.models import Room
from push.services import send_to_user
from sms.providers.base import SmsError
from sms.service import send_sms

from .audience import Recipient, audience, rendered
from .placeholders import fill, missing_values, values_for

logger = logging.getLogger(__name__)

TEST_PREFIX = "[Essai] "


def _plain(text):
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold()


def find_target(query):
    """A room number or a resident name, typed in the composer.

    Return (room, None, ""), (None, person, ""), or (None, None, French error).
    """
    query = " ".join(query.split())
    if not query:
        return None, None, "Écrivez un numéro de chambre ou un nom."
    room = Room.objects.filter(number__iexact=query).first()
    if room:
        return room, None, ""
    words = query.split()
    people = User.objects.residents().filter(is_active=True)
    for word in words:
        people = people.filter(Q(first_name__icontains=word) | Q(last_name__icontains=word))
    people = list(people[:6])
    if not people:
        # Names typed without accents: "Ines" for "Inès".
        wanted = [_plain(w) for w in words]
        people = [
            person
            for person in User.objects.residents().filter(is_active=True)
            if all(w in _plain(person.first_name) or w in _plain(person.last_name) for w in wanted)
        ][:6]
    if len(people) == 1:
        return None, people[0], ""
    if not people:
        return (
            None,
            None,
            f"Aucune chambre ni aucun résident ne correspond à «\u00a0{query}\u00a0».",
        )
    names = ", ".join(person.get_full_name() or person.get_username() for person in people[:5])
    return (
        None,
        None,
        f"Plusieurs résidents correspondent à «\u00a0{query}\u00a0» : {names}. Précisez.",
    )


def sample_recipient(campaign, user, audience_=None):
    """The first recipient (for the previews), or the user themselves."""
    recipients = (audience_ or audience(campaign)).recipients
    return recipients[0] if recipients else Recipient(user, None, "none")


def send_test(campaign, user, *, by_sms=False):
    """Send the message to ``user`` only, as the first recipient will see it.

    Return a list of French result lines.
    """
    missing = missing_values(campaign)
    if missing:
        names = ", ".join(f"{{{name}}}" for name in missing)
        return [f"Rien n'est parti : indiquez d'abord la valeur de {names}."]
    sample = sample_recipient(campaign, user)
    body, sms = rendered(campaign, sample)
    title = fill(campaign.title, values_for(campaign, sample.user, sample.room))
    lines = []
    result = send_to_user(
        user,
        title=TEST_PREFIX + title,
        body=body,
        url=f"/equipe/messages/{campaign.pk}/",
        tag=f"test-{campaign.pk}",
    )
    if result.sent:
        s = "s" if result.sent > 1 else ""
        lines.append(f"Notification d'essai envoyée sur {result.sent} appareil{s}.")
    else:
        lines.append("Aucune notification d'essai : activez les notifications sur votre appareil.")
    if by_sms:
        if not user.phone:
            lines.append("Pas de SMS d'essai : aucun numéro sur votre fiche.")
        else:
            try:
                send_sms(user.phone, sms)
                lines.append("SMS d'essai envoyé sur votre téléphone.")
            except SmsError as error:
                logger.warning("Test SMS failed: %s", type(error).__name__)
                lines.append(f"Le SMS d'essai n'est pas parti : {error}")
    return lines
