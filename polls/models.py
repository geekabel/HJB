"""Anonymous polls (card T25).

A poll belongs to a message of type "Vote, avis". The question is the title of
the message. We record who voted (Participation, to refuse a second vote and
to remind only the others), never what they chose:

- no row per vote: each option keeps a counter, so there is no vote time
  or vote order to match with the participations;
- the comments have no author, no date and no order: each new one is put at
  a random place in the list;
- the participation keeps the day only, not the time.
"""

from django.conf import settings
from django.db import models


class Poll(models.Model):
    campaign = models.OneToOneField(
        "messaging.Campaign", on_delete=models.CASCADE, related_name="poll", verbose_name="message"
    )
    closes_at = models.DateTimeField("clôture du vote", null=True, blank=True)
    allow_comment = models.BooleanField("permettre un commentaire pour l'équipe", default=True)
    # Comments without author, date or order (see above).
    comments = models.JSONField("commentaires", default=list, blank=True, editable=False)

    class Meta:
        verbose_name = "vote"
        verbose_name_plural = "votes"

    def __str__(self):
        return str(self.campaign)


class Option(models.Model):
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name="options")
    label = models.CharField("choix", max_length=80)
    position = models.PositiveSmallIntegerField("ordre")
    votes = models.PositiveIntegerField("voix", default=0, editable=False)

    class Meta:
        verbose_name = "choix"
        verbose_name_plural = "choix"
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(fields=["poll", "position"], name="one_option_per_position")
        ]

    def __str__(self):
        return self.label


class Participation(models.Model):
    """Who voted: never what. The day only, not the time."""

    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name="participations")
    resident = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="poll_participations",
        verbose_name="résident",
    )
    voted_on = models.DateField("a voté le")

    class Meta:
        verbose_name = "participation"
        verbose_name_plural = "participations"
        constraints = [
            models.UniqueConstraint(fields=["poll", "resident"], name="one_vote_per_resident")
        ]

    def __str__(self):
        return f"{self.resident} · {self.poll}"
