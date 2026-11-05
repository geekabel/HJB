"""Staff area: for staff only, with a session verified by passkey (card T14).

The check works on URL prefixes: a new staff page is protected as soon as
it is under /equipe/. Views also keep their own permissions (roles).

Django docs: https://docs.djangoproject.com/en/6.1/topics/http/middleware/
"""

from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse

from .session_policy import is_resident


def staff_prefixes():
    return ("/equipe/", "/guide/")


def admin_prefix():
    return "/" + settings.ADMIN_URL


class StaffAreaMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info
        is_admin = path.startswith(admin_prefix())
        if is_admin or path.startswith(staff_prefixes()):
            denial = self.check(request, is_admin)
            if denial is not None:
                return denial
        return self.get_response(request)

    @staticmethod
    def check(request, is_admin):
        user = request.user
        if not user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        allowed = user.is_staff if is_admin else not is_resident(user)
        if not allowed:
            raise PermissionDenied
        if not user.is_verified():
            # Session without a passkey (an old password login, for example).
            params = urlencode({"next": request.get_full_path()})
            return redirect(f"{reverse('access:confirm')}?{params}")
        return None
