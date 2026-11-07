from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm
from django.urls import reverse
from django.utils import timezone

from audit.models import Action
from audit.service import log_action

from .models import ActivationCode, User
from .roles import STAFF_ROLES, Role, set_roles
from .sessions import close_all


class RolesField(forms.TypedMultipleChoiceField):
    """Role checkboxes: a person can have several roles."""

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


class HJBUserChangeForm(UserChangeForm):
    roles = RolesField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["roles"].initial = sorted(self.instance.roles)


class HJBUserCreationForm(forms.ModelForm):
    """Account creation without a password (card T14).

    The person activates their account with an activation code, then a
    passkey. The password is made unusable.
    """

    roles = RolesField()

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "phone")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_unusable_password()
        if commit:
            user.save()
        return user


@admin.register(User)
class HJBUserAdmin(UserAdmin):
    """Groups are roles: they are chosen with checkboxes."""

    form = HJBUserChangeForm
    add_form = HJBUserCreationForm

    list_display = ("username", "first_name", "last_name", "roles_column", "is_active")
    list_filter = ("groups", "is_active", "is_staff")
    search_fields = ("username", "first_name", "last_name", "email", "phone")

    fieldsets = (
        (None, {"fields": ("username",)}),
        ("Identité", {"fields": ("first_name", "last_name", "email", "phone")}),
        ("Rôles", {"fields": ("roles",)}),
        ("Accès technique", {"fields": ("is_active", "is_staff", "is_superuser")}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "first_name", "last_name", "phone", "roles"),
            },
        ),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("groups")

    # Who can change rights (T14 review): roles and access to the admin site
    # require the Administration role (manage_roles). The superuser status
    # requires being a superuser. Otherwise, a person who can only edit
    # accounts could give themselves all rights.

    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj)
        if self.has_manage_roles_permission(request):
            return fieldsets
        return tuple(
            (
                title,
                {
                    **options,
                    "fields": tuple(
                        "roles_column" if field == "roles" else field for field in options["fields"]
                    ),
                },
            )
            for title, options in fieldsets
        )

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if not self.has_manage_roles_permission(request):
            readonly += ["roles_column", "is_staff"]
        if not request.user.is_superuser:
            readonly.append("is_superuser")
        return readonly

    actions = ("issue_staff_code",)

    def has_manage_roles_permission(self, request):
        return request.user.has_perm("accounts.manage_roles")

    @admin.action(
        description="Générer un code d'activation (personnel)", permissions=["manage_roles"]
    )
    def issue_staff_code(self, request, queryset):
        """First access of a staff member: code, SMS, then passkey (T14).

        Residents get their code at the front desk, from their profile page.
        """
        from access.session_policy import is_resident
        from residents.views import activation_sheet

        from .activation_codes import issue_code

        if queryset.count() != 1:
            self.message_user(request, "Choisissez un seul compte.", messages.WARNING)
            return None
        person = queryset.get()
        if person.is_superuser and not request.user.is_superuser:
            self.message_user(
                request,
                "Seul un super-utilisateur peut générer le code d'un super-utilisateur.",
                messages.WARNING,
            )
            return None
        if not person.is_active:
            self.message_user(request, "Ce compte est désactivé.", messages.WARNING)
            return None
        if is_resident(person):
            self.message_user(
                request,
                "Ce compte est celui d'un résident : son code se génère depuis sa fiche.",
                messages.WARNING,
            )
            return None
        code = issue_code(person, by=request.user, request=request, for_staff=True)
        back_url = reverse("admin:accounts_user_change", args=[person.pk])
        return activation_sheet(request, person, code, back_url)

    @admin.display(description="rôles")
    def roles_column(self, obj):
        return obj.roles_label

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        if "roles" not in form.cleaned_data or not self.has_manage_roles_permission(request):
            return
        before, after = set_roles(form.instance, form.cleaned_data["roles"])
        if before != after:
            # Rights and session length change: the person logs in again.
            close_all(form.instance, keep=request.session.session_key)
            # A code only works for the right kind of account (T14): we cancel only
            # the ones that no longer match (front desk code of a new staff
            # member, or staff code of a former staff member).
            # Status computed from the new roles: the object's groups may
            # still be cached (prefetch_related of the list).
            person = form.instance
            resident = not (person.is_staff or person.is_superuser or after & STAFF_ROLES)
            ActivationCode.objects.valid().filter(user=person, for_staff=resident).update(
                cancelled_at=timezone.now()
            )
            if resident:
                # App codes are for staff only (T14c): a former staff member loses
                # theirs, and does not get it back with a new role later.
                from django_otp.plugins.otp_totp.models import TOTPDevice

                TOTPDevice.objects.filter(user=person).delete()
            log_action(
                Action.ROLES_CHANGED,
                target=form.instance,
                details={"before": sorted(before), "after": sorted(after)},
                request=request,
            )


@admin.register(ActivationCode)
class ActivationCodeAdmin(admin.ModelAdmin):
    """Read only: codes are issued from the resident's profile page."""

    list_display = ("user", "created_at", "expires_at", "used_at", "cancelled_at", "created_by")
    list_select_related = ("user", "created_by")
    exclude = ("digest",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
