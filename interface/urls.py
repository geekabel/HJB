from django.urls import path

from . import views

app_name = "interface"

urlpatterns = [
    path("", views.guide, name="guide"),
    path("resident/", views.guide_resident, name="guide-resident"),
]
