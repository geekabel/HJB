"""The photo files go when their row goes (a report deleted, a resident
erased): Django never deletes the file of a FileField on its own.
https://docs.djangoproject.com/en/6.1/ref/models/fields/#django.db.models.fields.files.FieldFile.delete
"""

from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import ReportPhoto


@receiver(post_delete, sender=ReportPhoto, dispatch_uid="reports.photo_file")
def delete_photo_file(sender, instance, **kwargs):
    name = instance.image.name
    storage = instance.image.storage
    if name:
        # After the commit: a rolled back deletion keeps its file.
        transaction.on_commit(lambda: storage.delete(name))
