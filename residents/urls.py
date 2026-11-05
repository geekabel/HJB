from django.urls import path

from . import views

app_name = "residents"

urlpatterns = [
    path("", views.liste, name="liste"),
    path("nouveau/", views.creer, name="creer"),
    path("<int:pk>/", views.fiche, name="fiche"),
]
