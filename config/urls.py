"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from access import views as access_views
from ui import pwa

urlpatterns = [
    path("", access_views.home, name="home"),
    # Installable application (card T18): at the root, for the scope of the worker.
    path("manifest.webmanifest", pwa.manifest, name="manifest"),
    path("sw.js", pwa.service_worker, name="service_worker"),
    path("favicon.ico", pwa.favicon),
    path("hors-ligne/", pwa.offline, name="offline"),
    path("installer/", pwa.install, name="install"),
    path(settings.ADMIN_URL, admin.site.urls),
    # Login by passkey (card T13).
    path("connexion/", include("access.urls")),
    # Resident area: account activation (cards T11 to T13).
    path("activer/", include("activation.urls")),
    # Resident area: wifi access of the room (card T16).
    path("wifi/", include("housing.urls")),
    # Style guide, for staff only.
    path("guide/", include("ui.urls")),
    # Staff area.
    path("equipe/journal/", include("audit.urls")),
    path("equipe/residents/", include("residents.urls")),
]
