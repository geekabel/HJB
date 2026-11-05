from django.contrib import admin

from .models import AuditEntry


@admin.register(AuditEntry)
class AuditEntryAdmin(admin.ModelAdmin):
    """Read only: the log is never created, changed or deleted here."""

    list_display = ("created_at", "actor_label", "action", "target_label", "ip_address")
    list_filter = ("action",)
    search_fields = ("actor_label", "target_label")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
