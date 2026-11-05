from django.contrib import admin

from .models import PushSubscription


@admin.register(PushSubscription)
class PushSubscriptionAdmin(admin.ModelAdmin):
    """Read only, without the endpoint and the keys (they let anyone send to the device)."""

    list_display = ("user", "device", "created_at", "last_success_at", "failures")
    list_select_related = ("user",)
    search_fields = ("user__username", "user__first_name", "user__last_name")
    fields = ("user", "device", "created_at", "last_success_at", "failures")
    readonly_fields = fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
