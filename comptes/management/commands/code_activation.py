"""Génère un code d'activation depuis le serveur (carte T14).

Sert surtout au premier administrateur, qui n'a encore aucune clé d'accès :

    python manage.py code_activation <identifiant> --telephone "06 12 34 56 78"

Le code s'affiche une seule fois. Doc Django :
https://docs.djangoproject.com/en/6.1/howto/custom-management-commands/
"""

from django.core.management.base import BaseCommand, CommandError

from comptes.activation import generer_code
from comptes.models import User
from connexion.session import est_resident


class Command(BaseCommand):
    help = "Génère un code d'activation pour un compte et l'affiche une seule fois."

    def add_arguments(self, parser):
        parser.add_argument("identifiant", help="Identifiant du compte (username).")
        parser.add_argument(
            "--telephone",
            help="Numéro à enregistrer d'abord (le code SMS de l'étape 2 y sera envoyé).",
        )

    def handle(self, *args, identifiant, **options):
        try:
            personne = User.objects.get(username=identifiant)
        except User.DoesNotExist:
            raise CommandError(f"Aucun compte « {identifiant} ».") from None
        if not personne.is_active:
            raise CommandError("Ce compte est désactivé.")
        if options.get("telephone"):
            from django.core.exceptions import ValidationError

            personne.telephone = options["telephone"]
            try:
                personne.full_clean(validate_unique=True, exclude=["password"])
            except ValidationError as erreur:
                raise CommandError(" ".join(erreur.messages)) from None
            personne.save(update_fields=["telephone"])
        if not personne.telephone:
            raise CommandError(
                "Ce compte n'a pas de numéro de téléphone : il en faut un pour le code SMS."
            )
        code = generer_code(personne, pour_personnel=not est_resident(personne))
        self.stdout.write(f"Code d'activation de {identifiant} : {code}")
        self.stdout.write("Valable 72 heures, une seule fois. À saisir sur la page /activer/.")
