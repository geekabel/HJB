"""Form rendering in the colors of the design system.

Django docs: https://docs.djangoproject.com/en/6.1/topics/forms/#reusable-field-group-templates
and https://docs.djangoproject.com/en/6.1/ref/forms/renderers/

Django already links the field to its help text and its errors (aria-describedby,
ids ``<id>_helptext`` and ``<id>_error``) and sets aria-invalid.
The ``field.html`` template keeps these ids.
"""

from django.forms.renderers import DjangoTemplates


class HJBFormRenderer(DjangoTemplates):
    field_template_name = "ui/forms/field.html"
