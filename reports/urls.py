from django.urls import path

from . import views

app_name = "reports_staff"

urlpatterns = [
    path("", views.board, name="board"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/prendre/", views.take, name="take"),
    path("<int:pk>/confier/", views.assign, name="assign"),
    path("<int:pk>/planifier/", views.plan, name="plan"),
    path("<int:pk>/fait/", views.done, name="done"),
    path("photo/<int:pk>/", views.photo, name="photo"),
]
