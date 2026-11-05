from django.urls import path

from . import api, views

app_name = "connexion"

urlpatterns = [
    path("", views.connexion, name="connexion"),
    path("confirmer/", views.confirmer, name="confirmer"),
    path("deconnexion/", views.deconnexion, name="deconnexion"),
    # Cérémonie WebAuthn (JSON), appelée par cle-acces.js.
    path("cle/debut/", api.DebutVerification.as_view(), name="verification_debut"),
    path("cle/fin/", api.FinVerification.as_view(), name="verification_fin"),
]
