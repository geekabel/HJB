from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm
from django.urls import reverse
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


class FormulaireCreation(forms.ModelForm):
    """Création d'un compte sans mot de passe (carte T14).

    La personne active son compte avec un code d'activation, puis une clé
    d'accès. Le mot de passe est rendu inutilisable.
    """

    roles = ChampRoles()

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "telephone")

    def save(self, commit=True):
        utilisateur = super().save(commit=False)
        utilisateur.set_unusable_password()
        if commit:
            utilisateur.save()
        return utilisateur


@admin.register(User)
class UtilisateurAdmin(UserAdmin):
    """Les groupes sont les rôles : on les choisit par cases à cocher."""

    form = FormulaireModification
    add_form = FormulaireCreation

    list_display = ("username", "first_name", "last_name", "liste_roles", "is_active")
    list_filter = ("groups", "is_active", "is_staff")
    search_fields = ("username", "first_name", "last_name", "email", "telephone")

    fieldsets = (
        (None, {"fields": ("username",)}),
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
                "fields": ("username", "first_name", "last_name", "telephone", "roles"),
            },
        ),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("groups")

    actions = ("generer_code_personnel",)

    def has_gerer_roles_permission(self, request):
        return request.user.has_perm("comptes.gerer_roles")

    @admin.action(
        description="Générer un code d'activation (personnel)", permissions=["gerer_roles"]
    )
    def generer_code_personnel(self, request, queryset):
        """Premier accès d'un membre du personnel : code, SMS, puis clé d'accès (T14).

        Les résidents reçoivent leur code à l'accueil, depuis leur fiche.
        """
        from connexion.session import est_resident
        from residents.views import feuille_code

        from .activation import generer_code

        if queryset.count() != 1:
            self.message_user(request, "Choisissez un seul compte.", messages.WARNING)
            return None
        personne = queryset.get()
        if not personne.is_active:
            self.message_user(request, "Ce compte est désactivé.", messages.WARNING)
            return None
        if est_resident(personne):
            self.message_user(
                request,
                "Ce compte est celui d'un résident : son code se génère depuis sa fiche.",
                messages.WARNING,
            )
            return None
        code = generer_code(personne, par=request.user, requete=request, pour_personnel=True)
        retour = reverse("admin:comptes_user_change", args=[personne.pk])
        return feuille_code(request, personne, code, retour)

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
