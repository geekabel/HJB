"""Admin site: staff verified by passkey, with no password (card T14).

Django docs: "Overriding the default admin site"
https://docs.djangoproject.com/en/6.1/ref/contrib/admin/#overriding-the-default-admin-site
"""

from django.contrib.admin import AdminSite
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme


class HJBAdminSite(AdminSite):
    site_header = "HJB Résidence · administration"
    site_title = "HJB Résidence"

    def has_permission(self, request):
        # is_verified() comes from django-otp (OTPMiddleware): true if the session
        # was opened or confirmed with a passkey.
        return super().has_permission(request) and request.user.is_verified()

    def login(self, request, extra_context=None):
        """No password form: login goes through /connexion/."""
        next_url = request.GET.get("next", "")
        if not url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        ):
            next_url = ""
        next_url = next_url or reverse("admin:index")
        if self.has_permission(request):
            return redirect(next_url)
        return redirect_to_login(next_url)
