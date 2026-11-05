"""Espace équipe : liste et fiche des résidents (maquette P5).

Réservé à la permission ``comptes.gerer_residents`` (Accueil, Administration).
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Prefetch, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET

from comptes.models import FILTRE_ETAT_COMPTE, EtatCompte, User
from comptes.roles import Role
from logement.models import Etage, Sejour

from .forms import FormulaireImport, FormulaireResident
from .importation import (
    EN_TETES,
    ErreurFichier,
    analyser,
    depuis_session,
    importer,
    lire_fichier,
    vers_session,
)

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


# --- Import CSV et Excel (carte T08) ------------------------------------------

CLE_SESSION_IMPORT = "import_residents"
TITRES_MODELE = ["Prénom", "Nom", "Téléphone", "Chambre", "Arrivée", "E-mail"]


@login_required
@permission_required("comptes.gerer_residents", raise_exception=True)
def import_fichier(request):
    """Étape 1 : envoi du fichier. Il est lu puis oublié : seules les lignes
    analysées sont gardées dans la session, jusqu'à la confirmation."""
    formulaire = FormulaireImport(request.POST or None, request.FILES or None)
    if request.method == "POST" and formulaire.is_valid():
        fichier = formulaire.cleaned_data["fichier"]
        try:
            lignes = analyser(lire_fichier(fichier))
        except ErreurFichier as erreur:
            formulaire.add_error("fichier", str(erreur))
        else:
            request.session[CLE_SESSION_IMPORT] = {
                "fichier": fichier.name[:100],
                "lignes": vers_session(lignes),
            }
            return redirect("residents:import_apercu")
    return render(
        request,
        "residents/import.html",
        {"actif": "residents", "formulaire": formulaire, "en_tetes": EN_TETES},
    )


@login_required
@permission_required("comptes.gerer_residents", raise_exception=True)
def import_apercu(request):
    """Étape 2 : aperçu ligne par ligne, puis import des lignes prêtes."""
    import_en_cours = request.session.get(CLE_SESSION_IMPORT)
    if not import_en_cours:
        return redirect("residents:import")
    lignes = depuis_session(import_en_cours["lignes"])
    pretes = [ligne.numero for ligne in lignes if ligne.prete]
    situation_changee = False

    if request.method == "POST":
        if request.POST.get("action") == "annuler":
            del request.session[CLE_SESSION_IMPORT]
            messages.info(request, "Import annulé. Aucune fiche n'a été créée.")
            return redirect("residents:import")
        vues = request.POST.get("pretes", "")
        if vues != ",".join(map(str, pretes)):
            # Une chambre ou un numéro a été pris depuis l'aperçu.
            situation_changee = True
        else:
            try:
                creees = importer(lignes)
            except ValidationError as erreur:
                messages.warning(request, f"Rien n'a été importé : {' '.join(erreur.messages)}")
            else:
                del request.session[CLE_SESSION_IMPORT]
                s = "s" if creees > 1 else ""
                messages.success(request, f"{creees} résident{s} importé{s}.")
                return redirect("residents:liste")

    return render(
        request,
        "residents/import.html",
        {
            "actif": "residents",
            "fichier": import_en_cours["fichier"],
            "lignes": lignes,
            "pretes": ",".join(map(str, pretes)),
            "nombre_pretes": len(pretes),
            "nombre_a_corriger": len(lignes) - len(pretes),
            "situation_changee": situation_changee,
        },
    )


@require_GET
@login_required
@permission_required("comptes.gerer_residents", raise_exception=True)
def import_modele(request):
    """Fichier modèle : les titres de colonnes, en CSV lisible par Excel (BOM et « ; »)."""
    reponse = HttpResponse(content_type="text/csv; charset=utf-8")
    reponse["Content-Disposition"] = 'attachment; filename="modele-import-residents.csv"'
    reponse.write("\ufeff" + ";".join(TITRES_MODELE) + "\r\n")
    return reponse
