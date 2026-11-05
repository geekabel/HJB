from django.urls import path

from . import resident_views

app_name = "rdv"

urlpatterns = [
    path("", resident_views.book, name="book"),
    path("<int:pk>/", resident_views.detail, name="detail"),
]
