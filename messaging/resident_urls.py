from django.urls import path

from . import resident_views

app_name = "inbox"

urlpatterns = [
    path("", resident_views.inbox_list, name="list"),
    path("tout-lu/", resident_views.read_all, name="read_all"),
    path("<int:pk>/", resident_views.message, name="message"),
]
