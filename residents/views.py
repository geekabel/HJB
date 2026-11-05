"""Espace équipe : liste et fiche des résidents (maquette P5).

Réservé à la permission ``comptes.gerer_residents`` (Accueil, Administration).
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render

from comptes.models import FILTRE_ETAT_COMPTE, EtatCompte, User
from comptes.roles import Role
from logement.models import Etage, Sejour

from .forms import FormulaireResident

RESIDENTS_PAR_PAGE = 50
SANS_CHAMBRE = "sans"


def _sejours_en_cours():
    return Sejour.objects.en_cours().select_related("chambre__etage")


def _residents():
    return (
        User.objects.residents()
        .prefetch_related(
            Prefetch("sejours", queryset=_sejours_en_cours(), to_attr="sejours_en_cours"),
            "groups",
        )
        .order_by("last_name", "first_name", "pk")
    )


def _filtrer(residents, recherche, etage, compte):
    en_cours = Sejour.objects.filter(resident=OuterRef("pk"), depart__isnull=True)
    for mot in recherche.split():
        residents = residents.filter(
            Q(first_name__icontains=mot)
            | Q(last_name__icontains=mot)
            | Exists(en_cours.filter(chambre__numero__iexact=mot))
        )
    if etage == SANS_CHAMBRE:
        residents = residents.exclude(Exists(en_cours))
    elif etage:
        residents = residents.filter(Exists(en_cours.filter(chambre__etage_id=etage)))
    if compte:
        residents = residents.filter(FILTRE_ETAT_COMPTE[compte])
    return residents


@login_required
@permission_required("comptes.gerer_residents", raise_exception=True)
def liste(request):
    recherche = request.GET.get("q", "").strip()[:100]
    etages = list(Etage.objects.all())
    etage = request.GET.get("etage", "")
    if etage != SANS_CHAMBRE and etage not in {str(e.pk) for e in etages}:
        etage = ""
    compte = request.GET.get("compte", "")
    if compte not in EtatCompte.values:
        compte = ""

    tous = User.objects.residents()
    compteurs = tous.aggregate(
        total=Count("pk"),
        **{etat: Count("pk", filter=q) for etat, q in FILTRE_ETAT_COMPTE.items()},
    )
    residents = _filtrer(_residents(), recherche, etage, compte)
    page = Paginator(residents, RESIDENTS_PAR_PAGE).get_page(request.GET.get("page"))
    for resident in page:
        resident.sejour = resident.sejours_en_cours[0] if resident.sejours_en_cours else None
        resident.est_moderateur = Role.MODERATEUR in resident.roles

    filtres = request.GET.copy()
    filtres.pop("page", None)
    return render(
        request,
        "residents/liste.html",
        {
            "actif": "residents",
            "page_obj": page,
            "compteurs": compteurs,
            "recherche": recherche,
            "etages": etages,
            "etage": etage,
            "etats": EtatCompte.choices,
            "compte": compte,
            "filtre_actif": bool(recherche or etage or compte),
            "parametres": filtres.urlencode(),
        },
    )


def _formulaire(request, resident):
    formulaire = FormulaireResident(request.POST or None, instance=resident)
    if request.method == "POST" and formulaire.is_valid():
        try:
            with transaction.atomic():
                resident = formulaire.enregistrer()
        except ValidationError as erreur:
            formulaire.ajouter_erreurs_sejour(erreur)
        else:
            return formulaire, resident
    return formulaire, None


@login_required
@permission_required("comptes.gerer_residents", raise_exception=True)
def creer(request):
    formulaire, resident = _formulaire(request, User())
    if resident:
        messages.success(request, f"La fiche de {resident.get_full_name()} est créée.")
        return redirect("residents:fiche", pk=resident.pk)
    return render(
        request,
        "residents/fiche.html",
        {"actif": "residents", "formulaire": formulaire, "resident": None},
    )


@login_required
@permission_required("comptes.gerer_residents", raise_exception=True)
def fiche(request, pk):
    resident = get_object_or_404(User.objects.residents(), pk=pk)
    formulaire, enregistre = _formulaire(request, resident)
    if enregistre:
        messages.success(request, "Les modifications sont enregistrées.")
        return redirect("residents:fiche", pk=resident.pk)
    resident.refresh_from_db()  # le formulaire a pu modifier l'objet sans l'enregistrer
    return render(
        request,
        "residents/fiche.html",
        {
            "actif": "residents",
            "formulaire": formulaire,
            "resident": resident,
            "sejours": resident.sejours.select_related("chambre__etage"),
        },
    )
