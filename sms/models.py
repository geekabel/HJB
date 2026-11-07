from django.db import models


class SmsDailyUsage(models.Model):
    """SMS sent on one day (local time), to hold the daily limit.

    One row per day. ``segments`` counts what the operator bills: a long
    message counts for several SMS.
    """

    day = models.DateField("jour", unique=True)
    segments = models.PositiveIntegerField("SMS envoyés", default=0)

    class Meta:
        verbose_name = "SMS du jour"
        verbose_name_plural = "SMS par jour"

    def __str__(self):
        return f"{self.day} : {self.segments} SMS"
