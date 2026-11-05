from django.urls import path

from . import views

app_name = "push"

urlpatterns = [
    path("", views.settings_page, name="settings"),
    path("abonnement/", views.subscribe, name="subscribe"),
    path("desabonnement/", views.unsubscribe, name="unsubscribe"),
    path("essai/", views.send_test, name="test"),
    path("appareils/<int:pk>/supprimer/", views.remove_device, name="remove_device"),
]
