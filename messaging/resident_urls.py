from django.urls import path

from . import resident_views

app_name = "inbox"

urlpatterns = [
    path("<int:pk>/", resident_views.message, name="message"),
]
