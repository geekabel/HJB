from django.urls import path

from . import views

app_name = "residents"

urlpatterns = [
    path("", views.liste, name="liste"),
    path("nouveau/", views.creer, name="creer"),
    path("<int:pk>/", views.fiche, name="fiche"),
    path("<int:pk>/depart/", views.depart, name="depart"),
    path("<int:pk>/retour/", views.retour, name="retour"),
    path("<int:pk>/code-activation/", views.code_activation, name="code_activation"),
    path(
        "<int:pk>/code-activation/feuille/",
        views.code_activation_feuille,
        name="code_activation_feuille",
    ),
    path("import/", views.import_fichier, name="import"),
    path("import/apercu/", views.import_apercu, name="import_apercu"),
    path("import/modele.csv", views.import_modele, name="import_modele"),
]
