from django.urls import path

from . import resident_views

app_name = "reports"

urlpatterns = [
    path("", resident_views.overview, name="list"),
    path("nouveau/", resident_views.new, name="new"),
    path("<int:pk>/", resident_views.detail, name="detail"),
    path("photo/<int:pk>/", resident_views.photo, name="photo"),
    path("<int:pk>/regle/", resident_views.confirm, name="confirm"),
    path("<int:pk>/pas-encore/", resident_views.reopen, name="reopen"),
    path("<int:pk>/relancer/", resident_views.remind, name="remind"),
]
