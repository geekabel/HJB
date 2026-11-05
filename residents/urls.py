from django.urls import path

from . import views

app_name = "residents"

urlpatterns = [
    path("", views.liste, name="liste"),
    path("nouveau/", views.creer, name="creer"),
    path("<int:pk>/", views.fiche, name="fiche"),
    path("import/", views.import_fichier, name="import"),
    path("import/apercu/", views.import_apercu, name="import_apercu"),
    path("import/modele.csv", views.import_modele, name="import_modele"),
]
