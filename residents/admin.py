from django.contrib import admin

from .models import ImportResidents


@admin.register(ImportResidents)
class ImportResidentsAdmin(admin.ModelAdmin):
    """Historique en lecture seule."""

    list_display = ("importe_le", "fichier", "nombre", "importe_par")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
