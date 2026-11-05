from django.urls import path

from . import views

app_name = "messaging"

urlpatterns = [
    path("", views.campaign_list, name="list"),
    path("nouveau/", views.compose, name="new"),
    path("<int:pk>/", views.compose, name="compose"),
    path("<int:pk>/supprimer/", views.campaign_delete, name="delete"),
    path("<int:pk>/envoyer/", views.review, name="review"),
    path("<int:pk>/suivi/", views.tracking, name="tracking"),
    path("<int:pk>/annuler/", views.cancel, name="cancel"),
    path("modeles/", views.template_list, name="templates"),
    path("modeles/nouveau/", views.template_edit, name="template_new"),
    path("modeles/<int:pk>/", views.template_edit, name="template_edit"),
    path("modeles/<int:pk>/supprimer/", views.template_delete, name="template_delete"),
]
