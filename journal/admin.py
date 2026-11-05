from django.contrib import admin

from .models import EntreeJournal


@admin.register(EntreeJournal)
class EntreeJournalAdmin(admin.ModelAdmin):
    """Lecture seule : le journal ne se crée, ne se modifie et ne se supprime pas ici."""

    list_display = ("cree_le", "acteur_libelle", "action", "cible_libelle", "adresse_ip")
    list_filter = ("action",)
    search_fields = ("acteur_libelle", "cible_libelle")
    date_hierarchy = "cree_le"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
