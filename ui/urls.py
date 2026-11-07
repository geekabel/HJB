from django.urls import path

from . import views

app_name = "ui"

urlpatterns = [
    path("", views.guide, name="guide"),
    path("resident/", views.guide_resident, name="guide_resident"),
]
