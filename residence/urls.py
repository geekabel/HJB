from django.urls import path

from . import views

app_name = "residence"

urlpatterns = [
    path("", views.edit, name="edit"),
]
