from django.db import models
from django_otp.plugins.otp_totp.models import TOTPDevice


class AppCodeGuard(models.Model):
    """Wrong app codes since the last right one (card T37).

    django-otp slows the tries down; this stops them: after HARD_LIMIT wrong
    codes in a row, the app code no longer opens the account. The person
    logs in with their passkey and links the app again, or an administrator
    deletes the app in the admin site. A new app gets a new guard.
    """

    device = models.OneToOneField(
        TOTPDevice, on_delete=models.CASCADE, related_name="guard", verbose_name="application"
    )
    failures = models.PositiveIntegerField("codes faux d'affilée", default=0)
    locked_at = models.DateTimeField("bloquée le", null=True, blank=True)

    class Meta:
        verbose_name = "verrou d'une application de codes"
        verbose_name_plural = "verrous des applications de codes"

    def __str__(self):
        return f"Verrou de {self.device}"
