"""Étages, chambres et séjours de la résidence.

Le compte appartient à la personne ; la chambre est portée par le séjour.
Un séjour « en cours » n'a pas de date de départ.

Contraintes : https://docs.djangoproject.com/en/6.1/ref/models/constraints/
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Exists, F, OuterRef, Q
from django.utils import timezone


def libelle_court_etage(numero):
    """« RDC », « 1er », « 3e » : pour les listes."""
    if numero == 0:
        return "RDC"
    return "1er" if numero == 1 else f"{numero}e"


class Etage(models.Model):
    numero = models.PositiveSmallIntegerField(
        "numéro", unique=True, help_text="0 pour le rez-de-chaussée."
    )
    nom = models.CharField("nom", max_length=60, blank=True, help_text="Facultatif.")
    ordre_visite = models.PositiveSmallIntegerField(
        "ordre de visite",
        default=0,
        help_text="Ordre de passage dans la rotation des visites de chambres.",
    )

    class Meta:
        verbose_name = "étage"
        verbose_name_plural = "étages"
        ordering = ["numero"]

    def __str__(self):
        if self.nom:
            return self.nom
        if self.numero == 0:
            return "Rez-de-chaussée"
        return f"{libelle_court_etage(self.numero)} étage"

    @property
    def libelle_court(self):
        return libelle_court_etage(self.numero)


class ChambreQuerySet(models.QuerySet):
    def libres(self):
        """Chambres ouvertes sans séjour en cours."""
        # Exists plutôt qu'un exclude() sur la relation : une chambre sans aucun
        # séjour donnerait un départ « vide » dans la jointure.
        occupee = Sejour.objects.filter(chambre=OuterRef("pk"), depart__isnull=True)
        return self.filter(active=True).exclude(Exists(occupee))


class Chambre(models.Model):
    numero = models.CharField("numéro", max_length=10, unique=True)
    etage = models.ForeignKey(
        Etage, on_delete=models.PROTECT, related_name="chambres", verbose_name="étage"
    )
    active = models.BooleanField(
        "ouverte",
        default=True,
        help_text="Décocher pour une chambre fermée (travaux, bureau…). Elle garde son historique.",
    )

    objects = ChambreQuerySet.as_manager()

    class Meta:
        verbose_name = "chambre"
        verbose_name_plural = "chambres"
        ordering = ["etage__numero", "numero"]

    def __str__(self):
        return f"Chambre {self.numero}"

    def clean(self):
        self.numero = self.numero.strip().upper()


class SejourQuerySet(models.QuerySet):
    def en_cours(self):
        return self.filter(depart__isnull=True)


class Sejour(models.Model):
    resident = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sejours",
        verbose_name="résident",
    )
    chambre = models.ForeignKey(
        Chambre, on_delete=models.PROTECT, related_name="sejours", verbose_name="chambre"
    )
    arrivee = models.DateField("arrivée", default=timezone.localdate)
    depart = models.DateField(
        "départ", null=True, blank=True, help_text="Vide si le séjour est en cours."
    )

    objects = SejourQuerySet.as_manager()

    class Meta:
        verbose_name = "séjour"
        verbose_name_plural = "séjours"
        ordering = ["-arrivee", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["chambre"],
                condition=Q(depart__isnull=True),
                name="un_sejour_en_cours_par_chambre",
                violation_error_code="chambre_occupee",
                violation_error_message="Cette chambre a déjà un séjour en cours.",
            ),
            models.UniqueConstraint(
                fields=["resident"],
                condition=Q(depart__isnull=True),
                name="un_sejour_en_cours_par_resident",
                violation_error_code="resident_deja_loge",
                violation_error_message="Cette personne a déjà un séjour en cours.",
            ),
            models.CheckConstraint(
                condition=Q(depart__isnull=True) | Q(depart__gte=F("arrivee")),
                name="depart_apres_arrivee",
                violation_error_code="depart_avant_arrivee",
                violation_error_message="Le départ ne peut pas précéder l'arrivée.",
            ),
        ]

    def __str__(self):
        return f"{self.resident} ({self.chambre})"

    @property
    def en_cours(self):
        return self.depart is None

    def _chevauchements(self):
        """Autres séjours dont les dates croisent celles-ci (même jour de relève autorisé)."""
        autres = Sejour.objects.exclude(pk=self.pk).filter(
            Q(depart__isnull=True) | Q(depart__gt=self.arrivee)
        )
        if self.depart is not None:
            autres = autres.filter(arrivee__lt=self.depart)
        return autres

    def clean(self):
        if self.arrivee is None:
            return
        erreurs = {}
        croises = self._chevauchements()
        if self.en_cours:
            # Deux séjours en cours : déjà refusés par les contraintes uniques.
            croises = croises.filter(depart__isnull=False)
        if self.chambre_id is not None:
            if self.en_cours and not self.chambre.active:
                erreurs["chambre"] = ValidationError(
                    "Cette chambre est fermée.", code="chambre_fermee"
                )
            elif croises.filter(chambre_id=self.chambre_id).exists():
                erreurs["chambre"] = ValidationError(
                    "La chambre est occupée par quelqu'un d'autre sur ces dates.",
                    code="chambre_chevauchement",
                )
        if self.resident_id is not None and croises.filter(resident_id=self.resident_id).exists():
            erreurs["resident"] = ValidationError(
                "Cette personne a un autre séjour sur ces dates.",
                code="resident_chevauchement",
            )
        if erreurs:
            raise ValidationError(erreurs)
