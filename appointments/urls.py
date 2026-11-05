from django.urls import path

from . import views

app_name = "appointments"

urlpatterns = [
    path("", views.my_availability, name="availability"),
    path("absences/", views.add_absence, name="add_absence"),
    path("messages/", views.conversations, name="conversations"),
    path("messages/<int:pk>/", views.conversation, name="conversation"),
    path("absences/<int:pk>/retirer/", views.delete_absence, name="delete_absence"),
]
