from django.contrib import admin
from django.db.models import Exists, OuterRef

from .models import Chambre, Etage, Sejour


class ChambreEnLigne(admin.TabularInline):
    model = Chambre
    extra = 3
    fields = ("numero", "active")


@admin.register(Etage)
class EtageAdmin(admin.ModelAdmin):
    list_display = ("__str__", "numero", "ordre_visite", "nombre_chambres")
    list_editable = ("ordre_visite",)
    inlines = (ChambreEnLigne,)

    @admin.display(description="chambres")
    def nombre_chambres(self, obj):
        return obj.chambres.count()


class FiltreOccupation(admin.SimpleListFilter):
    title = "occupation"
    parameter_name = "occupation"

    def lookups(self, request, model_admin):
        return [("libre", "Libre"), ("occupee", "Occupée")]

    def queryset(self, request, queryset):
        if self.value() == "libre":
            return queryset.filter(pk__in=Chambre.objects.libres())
        if self.value() == "occupee":
            # Une chambre fermée et vide n'est ni libre ni occupée. Exists, et non
            # sejours__depart__isnull : ce filtre garderait les chambres sans séjour.
            en_cours = Sejour.objects.filter(chambre=OuterRef("pk"), depart__isnull=True)
            return queryset.filter(Exists(en_cours))
        return queryset


@admin.register(Chambre)
class ChambreAdmin(admin.ModelAdmin):
    list_display = ("numero", "etage", "active", "occupant")
    list_filter = ("etage", "active", FiltreOccupation)
    search_fields = ("numero",)

    @admin.display(description="occupant")
    def occupant(self, obj):
        sejour = obj.sejours.en_cours().select_related("resident").first()
        return sejour.resident if sejour else "Libre"


class FiltreEnCours(admin.SimpleListFilter):
    title = "état"
    parameter_name = "etat"

    def lookups(self, request, model_admin):
        return [("en_cours", "En cours"), ("termine", "Terminé")]

    def queryset(self, request, queryset):
        if self.value() == "en_cours":
            return queryset.filter(depart__isnull=True)
        if self.value() == "termine":
            return queryset.filter(depart__isnull=False)
        return queryset


@admin.register(Sejour)
class SejourAdmin(admin.ModelAdmin):
    list_display = ("resident", "chambre", "arrivee", "depart")
    list_filter = (FiltreEnCours, "chambre__etage")
    list_select_related = ("resident", "chambre")
    search_fields = ("resident__first_name", "resident__last_name", "chambre__numero")
    autocomplete_fields = ("resident", "chambre")
    date_hierarchy = "arrivee"
