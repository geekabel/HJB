from django.urls import path

from . import views, wifi_import_views

app_name = "residents"

urlpatterns = [
    path("", views.resident_list, name="list"),
    path("nouveau/", views.create, name="create"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/depart/", views.departure, name="departure"),
    path("<int:pk>/retour/", views.return_view, name="return"),
    path("<int:pk>/code-activation/", views.activation_code, name="activation_code"),
    path("<int:pk>/couper-acces/", views.cut_access, name="cut_access"),
    path("<int:pk>/wifi/", views.wifi_access, name="wifi_access"),
    path("<int:pk>/wifi/mot-de-passe/", views.wifi_password, name="wifi_password"),
    path("import/", views.import_file, name="import"),
    path("import/apercu/", views.import_preview, name="import_preview"),
    path("import/modele.csv", views.import_template, name="import_template"),
    path("wifi/import/", wifi_import_views.wifi_import_file, name="wifi_import"),
    path("wifi/import/apercu/", wifi_import_views.wifi_import_preview, name="wifi_import_preview"),
    path(
        "wifi/import/modele.csv",
        wifi_import_views.wifi_import_template,
        name="wifi_import_template",
    ),
]
