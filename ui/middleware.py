"""Session middleware that leaves the public files of the application alone (card T18).

The browser fetches /sw.js on its own (update check, at most once a day, also
after a push from card T19). With SESSION_SAVE_EVERY_REQUEST, Django's
SessionMiddleware would then renew the session each time: a lost phone that
still gets notifications would stay logged in forever. These addresses carry
no personal data, so they get an empty session that is never saved, and the
session cookie is neither renewed nor deleted.
"""

from django.contrib.sessions.middleware import SessionMiddleware

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
        return super().process_response(request, response)


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
