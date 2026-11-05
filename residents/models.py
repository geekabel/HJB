from django.conf import settings
from django.db import models


class ImportResidents(models.Model):
    """Trace d'un import confirmé.

    Le jeton est unique : un double clic, ou deux onglets qui confirment le
    même aperçu, ne peuvent créer les fiches qu'une seule fois.
    """

    jeton = models.CharField(max_length=43, unique=True, editable=False)
    importe_le = models.DateTimeField("importé le", auto_now_add=True)
    importe_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
        verbose_name="importé par",
    )
    fichier = models.CharField("fichier", max_length=100)
    nombre = models.PositiveIntegerField("fiches créées", default=0)

    class Meta:
        verbose_name = "import de résidents"
        verbose_name_plural = "imports de résidents"
        ordering = ["-importe_le"]

    def __str__(self):
        return f"{self.fichier} ({self.nombre})"
