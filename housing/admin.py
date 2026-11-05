from django.contrib import admin
from django.db.models import Exists, OuterRef

from .models import Floor, Room, Stay


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
