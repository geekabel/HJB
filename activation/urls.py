from django.urls import path

from . import views

app_name = "activation"

urlpatterns = [
    path("", views.enter_code, name="enter_code"),
    path("telephone/", views.phone, name="phone"),
    path("telephone/pas-mon-numero/", views.wrong_number, name="wrong_number"),
    path("cle/", views.passkey, name="passkey"),
    path("application/", views.app_code_setup, name="app_code"),
    path("cle/debut/", views.passkey_begin, name="passkey_begin"),
    path("cle/fin/", views.passkey_complete, name="passkey_complete"),
]
