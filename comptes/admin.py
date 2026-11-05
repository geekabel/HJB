from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm
from django.utils import timezone

from journal.models import Action
from journal.service import journaliser

from .models import CodeActivation, User
from .roles import ROLES_EQUIPE, Role, definir_roles
from .sessions import fermer_toutes


class ChampRoles(forms.TypedMultipleChoiceField):
    """Cases à cocher des rôles : une personne peut en avoir plusieurs."""

    def __init__(self, **kwargs):
        super().__init__(
            choices=Role.choices,
            coerce=Role,
            required=False,
            widget=forms.CheckboxSelectMultiple,
            label="rôles",
            help_text="Une personne peut avoir plusieurs rôles. Aucun rôle : résident.",
            **kwargs,
        )


class FormulaireModification(UserChangeForm):
    roles = ChampRoles()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["roles"].initial = sorted(self.instance.roles)


class FormulaireCreation(AdminUserCreationForm):
    roles = ChampRoles()


@admin.register(User)
class UtilisateurAdmin(UserAdmin):
    """Les groupes sont les rôles : on les choisit par cases à cocher."""

    form = FormulaireModification
    add_form = FormulaireCreation

    list_display = ("username", "first_name", "last_name", "liste_roles", "is_active")
    list_filter = ("groups", "is_active", "is_staff")
    search_fields = ("username", "first_name", "last_name", "email", "telephone")

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Identité", {"fields": ("first_name", "last_name", "email", "telephone")}),
        ("Rôles", {"fields": ("roles",)}),
        ("Accès technique", {"fields": ("is_active", "is_staff", "is_superuser")}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "telephone", "roles", "password1", "password2"),
            },
        ),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("groups")

    @admin.display(description="rôles")
    def liste_roles(self, obj):
        return obj.libelle_roles

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        avant, apres = definir_roles(form.instance, form.cleaned_data.get("roles", []))
        if avant != apres:
            # Les droits et la durée de session changent : la personne se reconnecte.
            fermer_toutes(form.instance, sauf=request.session.session_key)
            if apres & ROLES_EQUIPE:
                # Les codes d'activation sont réservés aux résidents (voir T14).
                CodeActivation.objects.valides().filter(utilisateur=form.instance).update(
                    annule_le=timezone.now()
                )
            journaliser(
                Action.ROLES_MODIFIES,
                cible=form.instance,
                details={"avant": sorted(avant), "apres": sorted(apres)},
                requete=request,
            )


@admin.register(CodeActivation)
class CodeActivationAdmin(admin.ModelAdmin):
    """Lecture seule : les codes se génèrent depuis la fiche du résident."""

    list_display = ("utilisateur", "cree_le", "expire_le", "utilise_le", "annule_le", "cree_par")
    list_select_related = ("utilisateur", "cree_par")
    exclude = ("empreinte",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
