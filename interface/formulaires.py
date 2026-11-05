"""Rendu des formulaires aux couleurs du système de design.

Doc : https://docs.djangoproject.com/en/6.1/topics/forms/#reusable-field-group-templates
et https://docs.djangoproject.com/en/6.1/ref/forms/renderers/

Django relie déjà le champ à son aide et à ses erreurs (aria-describedby,
identifiants ``<id>_helptext`` et ``<id>_error``) et pose aria-invalid.
Le gabarit ``champ.html`` garde ces identifiants.
"""

from django.forms.renderers import DjangoTemplates


class RenduHJB(DjangoTemplates):
    field_template_name = "interface/formulaires/champ.html"
