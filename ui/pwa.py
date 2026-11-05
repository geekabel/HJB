"""Installable application (card T18): manifest, service worker, offline page.

Docs:
- Manifest: https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Manifest
- Installability: https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Guides/Making_PWAs_installable
- Service workers: https://developer.mozilla.org/en-US/docs/Web/API/Service_Worker_API

The service worker is served from the root (/sw.js), so that its scope is the
whole site. It keeps only public files in its cache (the offline page, the
style sheet, the fonts, the logo): never a page with personal data.
"""

import hashlib
import json
from functools import cache

from django.contrib.staticfiles import finders
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET

APP_NAME = "HJB Résidence"
# Light background of the design system (--bg): splash screen and title bar.
BACKGROUND = "#eef7fc"
OFFLINE_PATH = "/hors-ligne/"

# Public files kept by the service worker, to show the offline page.
PRECACHED_STATIC = (
    "ui/css/hjb.css",
    "ui/fonts/atkinson-hyperlegible-latin-400-normal.woff2",
    "ui/fonts/atkinson-hyperlegible-latin-700-normal.woff2",
    "ui/fonts/bricolage-grotesque-latin-wght-normal.woff2",
    "ui/icons/icon-192.png",
)


@require_GET
@cache_control(max_age=86400)
def manifest(request):
    data = {
        "id": "/",
        "name": APP_NAME,
        "short_name": "HJB",
        "description": (
            "Messages, rendez-vous, signalements et wifi de la résidence Habitat Jeunes Belfort."
        ),
        "lang": "fr",
        "dir": "ltr",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": BACKGROUND,
        "theme_color": BACKGROUND,
        "icons": [
            {"src": static("ui/icons/icon-192.png"), "sizes": "192x192", "type": "image/png"},
            {"src": static("ui/icons/icon-512.png"), "sizes": "512x512", "type": "image/png"},
            {
                "src": static("ui/icons/icon-maskable-512.png"),
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable",
            },
        ],
    }
    return JsonResponse(
        data,
        content_type="application/manifest+json",
        json_dumps_params={"ensure_ascii": False},
    )


@cache
def _cache_version():
    """Changes when a cached file changes: the new worker then replaces the old cache."""
    digest = hashlib.sha256(render_to_string("ui/offline.html").encode())
    for name in PRECACHED_STATIC:
        path = finders.find(name)
        if path:
            with open(path, "rb") as file:
                digest.update(file.read())
    return digest.hexdigest()[:12]


@require_GET
def service_worker(request):
    body = render_to_string(
        "ui/sw.js",
        {
            "version": _cache_version(),
            # JSON of fixed paths of this app: valid JavaScript literals.
            "offline_url_json": json.dumps(OFFLINE_PATH),
            "precache_json": json.dumps(
                [OFFLINE_PATH] + [static(name) for name in PRECACHED_STATIC]
            ),
        },
    )
    response = HttpResponse(body, content_type="text/javascript; charset=utf-8")
    # The browser checks for a new worker at each visit (MDN: "Updating your service worker").
    response["Cache-Control"] = "no-cache"
    return response


@require_GET
def offline(request):
    """Shown by the service worker when there is no network. No personal data."""
    return render(request, "ui/offline.html")


@require_GET
def install(request):
    """How to add the application to the home screen (needed for notifications on iPhone)."""
    return render(request, "ui/install.html")


@require_GET
def favicon(request):
    """Browsers ask for /favicon.ico even on pages without a link (admin site)."""
    return redirect(static("ui/icons/favicon.ico"), permanent=True)
