from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render

# Doc « Permissions and Authorization » : login_required, puis permission_required
# avec raise_exception. Une personne connectée sans le droit reçoit un 403 au lieu
# d'être renvoyée en boucle vers la page de connexion.


@login_required
@permission_required("comptes.acceder_espace_equipe", raise_exception=True)
def guide(request):
    """Guide de style : tous les composants, dans le gabarit de l'équipe."""
    return render(request, "interface/guide/index.html", {"a_traiter": 7})


@login_required
@permission_required("comptes.acceder_espace_equipe", raise_exception=True)
def guide_resident(request):
    """Accueil résident d'exemple, dans le gabarit mobile."""
    return render(request, "interface/guide/resident.html", {"actif": "accueil"})
