from urllib.parse import urlencode

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_http_methods

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
    change_form_template = "admin/accounts/user/change_form.html"

    def has_manage_roles_permission(self, request):
        return request.user.has_perm("accounts.manage_roles")

    def get_urls(self):
        return [
            path(
                "<int:object_id>/code-activation/",
                self.admin_site.admin_view(self.staff_code_view),
                name="accounts_user_staff_code",
            ),
            *super().get_urls(),
        ]

    def _staff_code_refusal(self, request, person):
        """Why no staff code can be given to ``person`` by this user, or ""."""
        from access.session_policy import is_resident

        if person.is_superuser and not request.user.is_superuser:
            return "Seul un super-utilisateur peut générer le code d'un super-utilisateur."
        if not person.is_active:
            return "Ce compte est désactivé."
        if is_resident(person):
            return "Ce compte est celui d'un résident : son code se génère depuis sa fiche."
        return ""

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        person = self.get_object(request, object_id)
        if (
            person is not None
            and self.has_manage_roles_permission(request)
            and not self._staff_code_refusal(request, person)
        ):
            extra_context["staff_code_url"] = reverse(
                "admin:accounts_user_staff_code", args=[person.pk]
            )
        return super().change_view(request, object_id, form_url, extra_context)

    def response_add(self, request, obj, post_url_continue=None):
        # The button is on the page that follows, for those who can use it.
        shown = "_addanother" not in request.POST and self.has_manage_roles_permission(request)
        if shown and set(obj.roles) & STAFF_ROLES:
            self.message_user(
                request,
                "Compte créé. Pour sa première connexion, la personne a besoin d'un code "
                "d'activation : bouton «\u00a0Code d'activation\u00a0» en haut de cette page.",
                messages.INFO,
            )
        return super().response_add(request, obj, post_url_continue)

    @method_decorator(require_http_methods(["GET", "POST"]))
    def staff_code_view(self, request, object_id):
        """First access of a staff member: a code to print, or sent by SMS (T14).

        Like a resident's code (T37), it needs a passkey (or app code) used
        less than 10 minutes ago: a code hands over the account.
        """
        from access.session_policy import confirmed_recently
        from residents.views import activation_sheet

        from .activation_codes import issue_code, send_code_by_sms

        if not self.has_manage_roles_permission(request):
            raise PermissionDenied
        person = get_object_or_404(User, pk=object_id)
        back_url = reverse("admin:accounts_user_change", args=[person.pk])
        refusal = self._staff_code_refusal(request, person)
        if refusal:
            self.message_user(request, refusal, messages.WARNING)
            return redirect(back_url)
        if not confirmed_recently(request):
            here = reverse("admin:accounts_user_staff_code", args=[person.pk])
            messages.info(request, "Confirmez d'abord votre identité.")
            return redirect(f"{reverse('access:confirm')}?{urlencode({'next': here})}")
        if request.method == "POST" and "sheet" in request.POST:
            code = issue_code(person, by=request.user, request=request, for_staff=True)
            return activation_sheet(request, person, code, back_url)
        if request.method == "POST" and "sms" in request.POST and not person.phone:
            self.message_user(request, "Ce compte n'a pas de numéro.", messages.WARNING)
            return redirect(back_url)
        if request.method == "POST" and "sms" in request.POST:
            address = request.build_absolute_uri(reverse("activation:enter_code"))
            if send_code_by_sms(person, address, by=request.user, request=request, for_staff=True):
                self.message_user(
                    request,
                    f"Code envoyé par SMS au {person.phone_display}. Il est valable 72 h.",
                    messages.SUCCESS,
                )
            else:
                self.message_user(
                    request,
                    "Le SMS n'est pas parti. Affichez le code et donnez-le en main propre.",
                    messages.WARNING,
                )
            return redirect(back_url)
        return TemplateResponse(
            request,
            "admin/accounts/user/staff_code.html",
            {
                **self.admin_site.each_context(request),
                "opts": self.opts,
                "original": person,
                "title": "Code d'activation",
                "back_url": back_url,
            },
        )

    @admin.action(
        description="Générer un code d'activation (personnel)", permissions=["manage_roles"]
    )
    def issue_staff_code(self, request, queryset):
        """First access of a staff member: code, SMS, then passkey (T14).

        Residents get their code at the front desk, from their profile page.
        """
        from residents.views import activation_sheet

        from .activation_codes import issue_code

        if queryset.count() != 1:
            self.message_user(request, "Choisissez un seul compte.", messages.WARNING)
            return None
        person = queryset.get()
        refusal = self._staff_code_refusal(request, person)
        if refusal:
            self.message_user(request, refusal, messages.WARNING)
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
