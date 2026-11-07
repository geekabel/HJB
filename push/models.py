from django.conf import settings
from django.db import models


class PushSubscription(models.Model):
    """One device (browser) that receives the notifications of a person (card T19).

    Created by the browser (Push API): the endpoint is the address of the
    browser's push service, p256dh and auth encrypt the message for this
    device only. Not secret on their own, but the endpoint lets anyone send
    to the device: it never appears in a page or a log.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="push_subscriptions",
        verbose_name="personne",
    )
    endpoint = models.URLField("adresse du service d'envoi", max_length=2048, unique=True)
    p256dh = models.CharField("clé publique de l'appareil", max_length=128)
    auth = models.CharField("secret d'authentification", max_length=64)
    device = models.CharField("appareil", max_length=100, blank=True)
    created_at = models.DateTimeField("activé le", auto_now_add=True)
    last_success_at = models.DateTimeField("dernier envoi réussi", null=True, blank=True)
    failures = models.PositiveSmallIntegerField("échecs d'affilée", default=0)

    class Meta:
        verbose_name = "appareil abonné aux notifications"
        verbose_name_plural = "appareils abonnés aux notifications"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} · {self.device or 'appareil'}"

    def as_subscription_info(self):
        """The dict expected by pywebpush.webpush()."""
        return {"endpoint": self.endpoint, "keys": {"p256dh": self.p256dh, "auth": self.auth}}
