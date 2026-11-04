from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render


@staff_member_required
def guide(request):
    """Guide de style : tous les composants, dans le gabarit de l'équipe."""
    return render(request, "interface/guide/index.html", {"a_traiter": 7})


@staff_member_required
def guide_resident(request):
    """Accueil résident d'exemple, dans le gabarit mobile."""
    return render(request, "interface/guide/resident.html", {"actif": "accueil"})
