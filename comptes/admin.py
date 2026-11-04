from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User
from .roles import synchroniser_groupes


@admin.register(User)
class UtilisateurAdmin(UserAdmin):
    """Les groupes découlent du rôle : on ne les modifie pas à la main ici."""

    list_display = ("username", "first_name", "last_name", "role", "is_active")
    list_filter = ("role", "est_moderateur", "is_active", "is_staff")
    search_fields = ("username", "first_name", "last_name", "email", "telephone")
    readonly_fields = ("groupes_du_role",)

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Identité", {"fields": ("first_name", "last_name", "email", "telephone")}),
        ("Rôle", {"fields": ("role", "est_moderateur", "groupes_du_role")}),
        (
            "Accès technique",
            {"fields": ("is_active", "is_staff", "is_superuser")},
        ),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "role", "telephone", "password1", "password2"),
            },
        ),
    )

    @admin.display(description="groupes (selon le rôle)")
    def groupes_du_role(self, obj):
        return ", ".join(obj.groups.order_by("name").values_list("name", flat=True)) or "aucun"

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        synchroniser_groupes(form.instance)
