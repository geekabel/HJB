"""Limite de tentatives de connexion, par adresse IP (carte T14).

Une clé d'accès ne se devine pas : il n'y a pas de mot de passe à essayer.
On ne bloque donc pas après des échecs (un tel blocage permettrait à une
seule personne d'empêcher tout le wifi de la résidence de se connecter).
On limite seulement les débuts de connexion, qui ouvrent chacun une session
en base : de quoi freiner un robot sans gêner les résidents.

- Le seuil est large, car tout le wifi de la résidence partage souvent une
  seule adresse.
- Une adresse IPv6 compte pour son réseau /64 : un client ne peut pas
  changer d'adresse pour contourner la limite.
- Derrière un proxy, REMOTE_ADDR est l'adresse du proxy : l'adresse réelle
  du client doit être réglée avant la mise en ligne (carte T38).
- Le compteur vit dans le cache de Django (en mémoire par processus tant
  qu'aucun cache partagé n'est choisi, T38).

Doc Django : https://docs.djangoproject.com/en/6.1/topics/cache/#the-low-level-cache-api
Doc Python : https://docs.python.org/3/library/ipaddress.html
"""

import ipaddress

from django.core.cache import cache

DEBUTS_MAX = 300  # débuts de connexion par adresse…
FENETRE_DEBUTS = 10 * 60  # …sur 10 minutes


def groupe(adresse):
    """L'adresse IPv4 telle quelle, ou le réseau /64 d'une adresse IPv6."""
    try:
        ip = ipaddress.ip_address(adresse or "")
    except ValueError:
        return "inconnue"
    if ip.version == 6:
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


def _cle(nom, adresse):
    return f"hjb:limite:{nom}:{groupe(adresse)}"


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
