from django.urls import path

from . import resident_views

app_name = "rdv"

urlpatterns = [
    path("", resident_views.overview, name="list"),
    path("reserver/", resident_views.book, name="book"),
    path("ecrire/", resident_views.educators_to_write, name="educators"),
    path("<int:pk>/", resident_views.detail, name="detail"),
    path("ecrire/<int:educator_pk>/", resident_views.write, name="write"),
    path("ecrire/<int:educator_pk>/nouveaux/", resident_views.write_newer, name="write_newer"),
    path("<int:pk>/annuler/", resident_views.cancel, name="cancel"),
]
