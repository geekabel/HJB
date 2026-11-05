from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone


class Action(models.TextChoices):
    ROLES_MODIFIES = "ROLES_MODIFIES", "Rôles modifiés"
    CODE_ACTIVATION_GENERE = "CODE_ACTIVATION_GENERE", "Code d'activation généré"
    CODE_WIFI_AFFICHE = "CODE_WIFI_AFFICHE", "Mot de passe wifi affiché"
    DEPART_RESIDENT = "DEPART_RESIDENT", "Départ d'un résident"
    RETOUR_RESIDENT = "RETOUR_RESIDENT", "Retour d'un ancien résident"
    CLE_ACCES_CREEE = "CLE_ACCES_CREEE", "Clé d'accès créée"
    ACCES_COUPE = "ACCES_COUPE", "Accès coupé (téléphone perdu)"


class EntreeJournalNonModifiable(Exception):
    """Une entrée du journal ne se modifie pas et ne se supprime pas une par une."""


class EntreeJournal(models.Model):
    """Une action sensible : qui, quoi, sur quoi, quand, depuis quelle adresse.

    L'entrée garde des libellés lisibles (acteur, cible) pour rester
    compréhensible même si le compte ou l'objet concerné est supprimé.
    Relation générique : doc « The contenttypes framework ».
    """

    cree_le = models.DateTimeField("date", default=timezone.now, db_index=True, editable=False)
    acteur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="acteur",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="actions_journalisees",
    )
    acteur_libelle = models.CharField("acteur (au moment de l'action)", max_length=150, blank=True)
    action = models.CharField(max_length=40, choices=Action.choices, db_index=True)
    # Un journal ne doit pas disparaître avec un type d'objet : PROTECT.
    cible_type = models.ForeignKey(
        ContentType, null=True, blank=True, on_delete=models.PROTECT, verbose_name="type de cible"
    )
    # Texte : compatible avec toute clé primaire (doc contenttypes).
    cible_id = models.CharField("identifiant de la cible", max_length=64, blank=True)
    cible = GenericForeignKey("cible_type", "cible_id")
    cible_libelle = models.CharField("cible (au moment de l'action)", max_length=200, blank=True)
    details = models.JSONField("détails", default=dict, blank=True)
    adresse_ip = models.GenericIPAddressField("adresse IP", null=True, blank=True)

    class Meta:
        verbose_name = "entrée du journal"
        verbose_name_plural = "journal d'audit"
        ordering = ["-cree_le", "-id"]
        indexes = [models.Index(fields=["cible_type", "cible_id"])]

    def __str__(self):
        return f"{self.cree_le:%d/%m/%Y %H:%M} · {self.get_action_display()} · {self.cible_libelle}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise EntreeJournalNonModifiable("Une entrée du journal ne se modifie pas.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise EntreeJournalNonModifiable(
            "Une entrée du journal ne se supprime pas une par une. "
            "La purge selon la durée de conservation est prévue en T36."
        )

    def resume(self):
        """Détails en clair, pour la page du journal."""
        if self.action == Action.ROLES_MODIFIES:
            from comptes.roles import Role

            def libelles(codes):
                return ", ".join(Role(c).label for c in codes) or "aucun (résident)"

            return (
                f"Avant : {libelles(self.details.get('avant', []))}. "
                f"Après : {libelles(self.details.get('apres', []))}."
            )
        if self.action == Action.RETOUR_RESIDENT:
            from datetime import date

            jour = date.fromisoformat(self.details["arrivee"])
            return f"Chambre {self.details.get('chambre', '?')}, retour le {jour:%d/%m/%Y}."
        if self.action == Action.CODE_ACTIVATION_GENERE and "expire_le" in self.details:
            from datetime import datetime

            from django.utils import timezone

            fin = timezone.localtime(datetime.fromisoformat(self.details["expire_le"]))
            return f"Valable jusqu'au {fin:%d/%m/%Y à %H:%M}."
        if self.action == Action.DEPART_RESIDENT:
            from datetime import date

            morceaux = []
            if self.details.get("chambre"):
                morceaux.append(f"Chambre {self.details['chambre']}")
            if self.details.get("depart"):
                jour = date.fromisoformat(self.details["depart"])
                morceaux.append(f"départ le {jour:%d/%m/%Y}")
            sessions = self.details.get("sessions_fermees", 0)
            texte = ", ".join(morceaux)
            texte = texte[:1].upper() + texte[1:] + "."
            if sessions:
                s = "s" if sessions > 1 else ""
                texte += f" {sessions} session{s} fermée{s}."
            cles = self.details.get("cles_retirees", 0)
            if cles:
                s = "s" if cles > 1 else ""
                texte += f" {cles} clé{s} d'accès supprimée{s}."
            return texte.strip()
        if self.action == Action.ACCES_COUPE:
            cles = self.details.get("cles_retirees", 0)
            sessions = self.details.get("sessions_fermees", 0)
            sc, ss = ("s" if cles > 1 else ""), ("s" if sessions > 1 else "")
            return f"{cles} clé{sc} d'accès supprimée{sc}, {sessions} session{ss} fermée{ss}."
        if self.action == Action.CLE_ACCES_CREEE:
            anciennes = self.details.get("anciennes_retirees", 0)
            if not anciennes:
                return "Première clé d'accès."
            s = "s" if anciennes > 1 else ""
            return f"Remplace {anciennes} ancienne{s} clé{s}, désormais inutilisable{s}."
        return " · ".join(f"{cle} : {valeur}" for cle, valeur in self.details.items())
