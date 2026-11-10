from django.urls import path

from . import views

app_name = "appointments"

urlpatterns = [
    path("", views.my_availability, name="availability"),
    path("absences/", views.add_absence, name="add_absence"),
    path("rendez-vous/<int:pk>/annuler/", views.cancel_meeting, name="cancel_meeting"),
    path("messages/", views.conversations, name="conversations"),
    path("messages/<int:pk>/", views.conversation, name="conversation"),
    path("messages/<int:pk>/nouveaux/", views.conversation_newer, name="conversation_newer"),
    path("absences/<int:pk>/retirer/", views.delete_absence, name="delete_absence"),
]
