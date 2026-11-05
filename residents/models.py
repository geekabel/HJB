from django.conf import settings
from django.db import models


class ResidentImport(models.Model):
    """Record of a confirmed import.

    The token is unique: a double click, or two tabs that confirm the same
    preview, can only create the residents once.
    """

    token = models.CharField("jeton", max_length=43, unique=True, editable=False)
    imported_at = models.DateTimeField("importé le", auto_now_add=True)
    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
        verbose_name="importé par",
    )
    file_name = models.CharField("fichier", max_length=100)
    count = models.PositiveIntegerField("fiches créées", default=0)

    class Meta:
        verbose_name = "import de résidents"
        verbose_name_plural = "imports de résidents"
        ordering = ["-imported_at"]

    def __str__(self):
        return f"{self.file_name} ({self.count})"
