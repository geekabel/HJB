"""Espace équipe : réservé au personnel, avec une session vérifiée par clé d'accès (carte T14).

Le contrôle porte sur des préfixes d'adresse : une nouvelle page de l'équipe
est protégée dès qu'elle est sous /equipe/. Les vues gardent leurs propres
permissions (rôles) en plus.

Doc Django : https://docs.djangoproject.com/en/6.1/topics/http/middleware/
"""

from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse

from .session import est_resident


def prefixes_equipe():
    return ("/equipe/", "/guide/")


def prefixe_administration():
    return "/" + settings.ADMIN_URL


class EspaceEquipeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        chemin = request.path_info
        administration = chemin.startswith(prefixe_administration())
        if administration or chemin.startswith(prefixes_equipe()):
            refus = self.controler(request, administration)
            if refus is not None:
                return refus
        return self.get_response(request)

    @staticmethod
    def controler(request, administration):
        utilisateur = request.user
        if not utilisateur.is_authenticated:
            return redirect_to_login(request.get_full_path())
        autorise = utilisateur.is_staff if administration else not est_resident(utilisateur)
        if not autorise:
            raise PermissionDenied
        if not utilisateur.is_verified():
            # Session sans clé d'accès (ancienne connexion par mot de passe, par exemple).
            parametres = urlencode({"next": request.get_full_path()})
            return redirect(f"{reverse('connexion:confirmer')}?{parametres}")
        return None
