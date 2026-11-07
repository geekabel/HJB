from django.urls import path

from . import api, views

app_name = "access"

urlpatterns = [
    path("", views.login_view, name="login"),
    path("confirmer/", views.confirm, name="confirm"),
    path("code/", views.login_app_code, name="login_app_code"),
    path("deconnexion/", views.logout_view, name="logout"),
    # WebAuthn ceremony (JSON), called by passkey.js.
    path("cle/debut/", api.VerifyBeginView.as_view(), name="verify_begin"),
    path("cle/fin/", api.VerifyCompleteView.as_view(), name="verify_complete"),
]
