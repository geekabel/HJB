"""Session middleware that leaves the public files of the application alone (card T18).

The browser fetches /sw.js on its own (update check, at most once a day, also
after a push from card T19). With SESSION_SAVE_EVERY_REQUEST, Django's
SessionMiddleware would then renew the session each time: a lost phone that
still gets notifications would stay logged in forever. These addresses carry
no personal data, so they get an empty session that is never saved, and the
session cookie is neither renewed nor deleted.

The same goes for the requests a page makes on its own (@background views,
such as the new messages of a conversation): they keep the session, but do
not renew it.
"""

from functools import wraps

from django.contrib.sessions.middleware import SessionMiddleware
from django.utils.cache import add_never_cache_headers, patch_vary_headers

SESSIONLESS_PATHS = frozenset({"/sw.js", "/manifest.webmanifest", "/hors-ligne/", "/favicon.ico"})


class PublicFilesSessionMiddleware(SessionMiddleware):
    def process_request(self, request):
        if request.path_info in SESSIONLESS_PATHS:
            request.session = self.SessionStore()  # empty: the visitor is anonymous here
            request.sessionless = True
            return
        super().process_request(request)

    def process_response(self, request, response):
        if getattr(request, "sessionless", False):
            return response
        if getattr(request, "background", False) and not request.session.modified:
            # A page that asks on its own (thread.js) is not activity: the
            # session keeps its expiry, and is not written every 5 seconds.
            patch_vary_headers(response, ("Cookie",))
            return response
        return super().process_response(request, response)


def background(view):
    """Mark a view called by a script, not by the person (see above)."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        request.background = True
        return view(request, *args, **kwargs)

    return wrapper


# Browser features the site never asks for (card T37). A script injected
# despite the CSP could not use them either. Taking a photo for a report
# goes through <input type="file">, not the camera feature.
# https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Permissions-Policy
PERMISSIONS_POLICY = ", ".join(
    f"{feature}=()"
    for feature in ("camera", "microphone", "geolocation", "payment", "usb", "display-capture")
)


class PermissionsPolicyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
        return response


class PrivatePagesMiddleware:
    """A page shown to a logged-in person is never kept by the browser or
    a proxy (card T37): on a shared computer, after logout, the Back
    button must not show resident phone numbers again. A page that sets
    its own Cache-Control keeps it.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and "Cache-Control" not in response:
            add_never_cache_headers(response)
        return response
