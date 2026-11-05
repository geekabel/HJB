from django.urls import path

from . import views

app_name = "housing"

urlpatterns = [
    path("", views.my_wifi, name="my_wifi"),
    path("mot-de-passe/", views.my_wifi_password, name="my_wifi_password"),
]
