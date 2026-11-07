from django.contrib import admin
from django.db.models import Exists, OuterRef
from django.shortcuts import redirect
from django.urls import reverse

from .models import Floor, Room, Stay, WifiAccess, WifiSettings


class RoomInline(admin.TabularInline):
    model = Room
    extra = 3
    fields = ("number", "active")


@admin.register(Floor)
class FloorAdmin(admin.ModelAdmin):
    list_display = ("__str__", "number", "visit_order", "room_count")
    list_editable = ("visit_order",)
    inlines = (RoomInline,)

    @admin.display(description="chambres")
    def room_count(self, obj):
        return obj.rooms.count()


class OccupancyFilter(admin.SimpleListFilter):
    title = "occupation"
    parameter_name = "occupancy"

    def lookups(self, request, model_admin):
        return [("free", "Libre"), ("occupied", "Occupée")]

    def queryset(self, request, queryset):
        if self.value() == "free":
            return queryset.filter(pk__in=Room.objects.free())
        if self.value() == "occupied":
            # A closed and empty room is neither free nor occupied. Exists, and not
            # stays__departure__isnull: that filter would keep rooms with no stay.
            current = Stay.objects.filter(room=OuterRef("pk"), departure__isnull=True)
            return queryset.filter(Exists(current))
        return queryset


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("number", "floor", "active", "occupant")
    list_filter = ("floor", "active", OccupancyFilter)
    search_fields = ("number",)

    @admin.display(description="occupant")
    def occupant(self, obj):
        stay = obj.stays.current().select_related("resident").first()
        return stay.resident if stay else "Libre"


class CurrentFilter(admin.SimpleListFilter):
    title = "état"
    parameter_name = "state"

    def lookups(self, request, model_admin):
        return [("current", "En cours"), ("ended", "Terminé")]

    def queryset(self, request, queryset):
        if self.value() == "current":
            return queryset.filter(departure__isnull=True)
        if self.value() == "ended":
            return queryset.filter(departure__isnull=False)
        return queryset


@admin.register(Stay)
class StayAdmin(admin.ModelAdmin):
    list_display = ("resident", "room", "arrival", "departure")
    list_filter = (CurrentFilter, "room__floor")
    list_select_related = ("resident", "room")
    search_fields = ("resident__first_name", "resident__last_name", "room__number")
    autocomplete_fields = ("resident", "room")
    date_hierarchy = "arrival"


@admin.register(WifiAccess)
class WifiAccessAdmin(admin.ModelAdmin):
    """Read only, and never the password: accesses are recorded from the resident page."""

    list_display = ("room", "username", "created_on", "expires_on", "active", "end_reason")
    list_filter = ("active",)
    list_select_related = ("room",)
    search_fields = ("room__number", "username")
    exclude = ("encrypted_password",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WifiSettings)
class WifiSettingsAdmin(admin.ModelAdmin):
    """A single row: the format of the captive portal credentials (card T15b).

    Open to the role with manage_wifi_settings (Administration). The list page
    goes straight to the row; it is never added nor deleted here.
    """

    fieldsets = (
        (None, {"fields": ("network_name",)}),
        (
            "Format des accès générés",
            {
                "fields": ("username_length", "password_length", "alphabet"),
                "description": (
                    "Ces réglages servent seulement quand l'application génère un "
                    "identifiant ou un mot de passe. Les accès saisis à la main "
                    "restent libres, de 4 à 64 caractères sans espace."
                ),
            },
        ),
    )

    def _allowed(self, request):
        return request.user.has_perm("accounts.manage_wifi_settings")

    def has_module_permission(self, request):
        return self._allowed(request)

    def has_view_permission(self, request, obj=None):
        return self._allowed(request)

    def has_change_permission(self, request, obj=None):
        return self._allowed(request)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        if not self._allowed(request):
            return super().changelist_view(request, extra_context)  # refused there
        row = WifiSettings.load()
        return redirect(reverse("admin:housing_wifisettings_change", args=[row.pk]))
