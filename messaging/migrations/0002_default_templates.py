"""First message templates (card T20). The staff can change or delete them."""

from django.db import migrations

TEMPLATES = [
    {
        "type": "visit",
        "name": "Visite hebdomadaire · alarme et compteur",
        "title": "Visite de logement",
        "body": (
            "Bonjour {prénom},\n"
            "Le {date}, nous passerons dans votre logement entre {début} et {fin}.\n"
            "Nous vérifierons l'alarme incendie et le compteur.\n"
            "Merci de nous dire si vous serez présent.\n"
            "Bonne journée,\nL'équipe HJB"
        ),
        "sms_body": (
            "Bonjour {prénom}, visite de votre logement le {date} entre {début} et {fin} "
            "(alarme, compteur). L'équipe HJB"
        ),
        "reply_expected": True,
    },
    {
        "type": "visit",
        "name": "Visite annulée",
        "title": "Visite annulée",
        "body": (
            "Bonjour {prénom},\n"
            "La visite de votre logement prévue le {date} est annulée. "
            "Nous vous donnerons bientôt une nouvelle date.\n"
            "L'équipe HJB"
        ),
        "sms_body": "Bonjour {prénom}, la visite de votre logement du {date} est annulée. L'équipe HJB",
        "reply_expected": False,
    },
    {
        "type": "visit",
        "name": "Visite déplacée",
        "title": "Visite déplacée",
        "body": (
            "Bonjour {prénom},\n"
            "La visite de votre logement est déplacée au {date}, entre {début} et {fin}.\n"
            "Merci de nous dire si vous serez présent.\n"
            "L'équipe HJB"
        ),
        "sms_body": (
            "Bonjour {prénom}, la visite de votre logement est déplacée au {date}, "
            "entre {début} et {fin}. L'équipe HJB"
        ),
        "reply_expected": True,
    },
    {
        "type": "maintenance",
        "name": "Coupure d'eau",
        "title": "Coupure d'eau",
        "body": (
            "Bonjour {prénom},\n"
            "L'eau sera coupée le {date}, de {début} à {fin}, pour des travaux.\n"
            "Pensez à garder un peu d'eau de côté.\n"
            "L'équipe HJB"
        ),
        "sms_body": "Coupure d'eau le {date} de {début} à {fin} (travaux). L'équipe HJB",
        "reply_expected": False,
    },
    {
        "type": "announcement",
        "name": "Événement à la résidence",
        "title": "Événement à la résidence",
        "body": (
            "Bonjour {prénom},\n"
            "Vous êtes invité le {date} à {début} : décrivez ici l'événement et le lieu.\n"
            "À bientôt,\nL'équipe HJB"
        ),
        "sms_body": "",
        "reply_expected": False,
    },
    {
        "type": "vote",
        "name": "Votre avis",
        "title": "Votre avis compte",
        "body": (
            "Bonjour {prénom},\n"
            "Donnez votre avis dans l'application avant le {date}. Cela prend une minute.\n"
            "L'équipe HJB"
        ),
        "sms_body": "Bonjour {prénom}, donnez votre avis dans l'appli HJB avant le {date}.",
        "reply_expected": False,
    },
]


def add_templates(apps, schema_editor):
    MessageTemplate = apps.get_model("messaging", "MessageTemplate")
    for data in TEMPLATES:
        MessageTemplate.objects.get_or_create(type=data["type"], name=data["name"], defaults=data)


class Migration(migrations.Migration):
    dependencies = [("messaging", "0001_initial")]

    operations = [migrations.RunPython(add_templates, migrations.RunPython.noop)]
