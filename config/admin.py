"""Site d'administration : personnel vérifié par clé d'accès, sans mot de passe (carte T14).

Doc Django : « Overriding the default admin site »
https://docs.djangoproject.com/en/6.1/ref/contrib/admin/#overriding-the-default-admin-site
"""

from django.contrib.admin import AdminSite
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme


class SiteAdministration(AdminSite):
    site_header = "HJB Résidence · administration"
    site_title = "HJB Résidence"

    def has_permission(self, request):
        # is_verified() vient de django-otp (OTPMiddleware) : vrai si la session a
        # été ouverte ou confirmée avec une clé d'accès.
        return super().has_permission(request) and request.user.is_verified()

    def login(self, request, extra_context=None):
        """Pas de formulaire de mot de passe : la connexion passe par /connexion/."""
        suite = request.GET.get("next", "")
        if not url_has_allowed_host_and_scheme(
            suite, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        ):
            suite = ""
        suite = suite or reverse("admin:index")
        if self.has_permission(request):
            return redirect(suite)
        return redirect_to_login(suite)
