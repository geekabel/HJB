"""Limites de tentatives de connexion, par adresse IP (carte T14).

Une clé d'accès ne se devine pas : ces limites protègent surtout le serveur
(chaque début de connexion ouvre une session) et freinent les essais en
série. Elles restent larges, car tout le wifi de la résidence partage
souvent la même adresse.

Le compteur vit dans le cache de Django. Sans réglage CACHES, c'est un
cache en mémoire, propre à chaque processus : la limite vaut alors par
processus. Un cache partagé (Redis, base de données) sera choisi au
déploiement (T38).

Doc Django : https://docs.djangoproject.com/en/6.1/topics/cache/#the-low-level-cache-api
"""

from django.core.cache import cache

DEBUTS_MAX = 100  # débuts de connexion par adresse
FENETRE_DEBUTS = 10 * 60  # secondes
ECHECS_MAX = 30  # vérifications refusées par adresse
FENETRE_ECHECS = 60 * 60  # secondes


def _cle(nom, adresse):
    return f"hjb:limite:{nom}:{adresse or 'inconnue'}"


def atteinte(nom, adresse, maximum):
    """Vrai si ``maximum`` est déjà atteint pour cette adresse."""
    return cache.get(_cle(nom, adresse), 0) >= maximum


def noter(nom, adresse, fenetre):
    """Compte une tentative. Le compteur repart à zéro ``fenetre`` secondes après la première."""
    cle = _cle(nom, adresse)
    if not cache.add(cle, 1, fenetre):
        try:
            cache.incr(cle)
        except ValueError:  # expiré entre-temps
            cache.set(cle, 1, fenetre)
