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

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    # Espace résident : activation du compte (cartes T11 à T13).
    path("activer/", include("activation.urls")),
    # Guide de style, réservé à l'équipe.
    path("guide/", include("interface.urls")),
    # Espace équipe.
    path("equipe/journal/", include("journal.urls")),
    path("equipe/residents/", include("residents.urls")),
]
