from django.contrib import admin

from .models import ResidentImport


@admin.register(ResidentImport)
class ResidentImportAdmin(admin.ModelAdmin):
    """Read-only history."""

    list_display = ("imported_at", "file_name", "count", "imported_by")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
