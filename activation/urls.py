from django.urls import path

from . import views

app_name = "activation"

urlpatterns = [
    path("", views.saisie, name="saisie"),
    path("telephone/", views.telephone, name="telephone"),
]
