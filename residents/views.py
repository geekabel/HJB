"""Espace équipe : liste et fiche des résidents (maquette P5).

Consultation : permission ``comptes.voir_residents`` (Accueil, Éducateurs,
Administration). Création, modification, import et départ :
``comptes.gerer_residents`` (Accueil, Administration).
"""

import secrets
import time

import segno
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, OuterRef, Prefetch, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.cache import add_never_cache_headers
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_GET, require_POST

from comptes.activation import (
    DUREE_VALIDITE,
    envoyer_code_par_sms,
    etat_activation,
    generer_code,
)
from comptes.models import FILTRE_ETAT_COMPTE, EtatCompte, User
from comptes.roles import Role
from logement.models import Etage, Sejour
from logement.services import sejour_en_cours

from .depart import enregistrer_depart, enregistrer_retour, est_parti
from .forms import FormulaireDepart, FormulaireImport, FormulaireResident, FormulaireRetour
from .importation import (
    EN_TETES,
    ErreurFichier,
    analyser,
    depuis_session,
    importer,
    lire_fichier,
    vers_session,
)
from .models import ImportResidents

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


def _anciens():
    """Anciens résidents : compte désactivé et plus de séjour en cours.

    Un compte désactivé mais encore logé reste dans la liste : son départ
    n'est pas fini (la chambre n'est pas libérée).
    """
    en_cours = Sejour.objects.filter(resident=OuterRef("pk"), depart__isnull=True)
    return Q(is_active=False) & ~Exists(en_cours)


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
@permission_required("comptes.voir_residents", raise_exception=True)
def liste(request):
    recherche = request.GET.get("q", "").strip()[:100]
    etages = list(Etage.objects.all())
    etage = request.GET.get("etage", "")
    if etage != SANS_CHAMBRE and etage not in {str(e.pk) for e in etages}:
        etage = ""
    peut_gerer = request.user.has_perm("comptes.gerer_residents")
    etats = EtatCompte.choices
    if not peut_gerer:
        # Les éducateurs ne voient que les résidents actuels (minimisation des données).
        etats = [choix for choix in etats if choix[0] != EtatCompte.DESACTIVE]
    compte = request.GET.get("compte", "")
    if compte not in dict(etats):
        compte = ""

    tous = User.objects.residents()
    compteurs = tous.aggregate(
        total=Count("pk"),
        anciens=Count("pk", filter=_anciens()),
        **{etat: Count("pk", filter=q) for etat, q in FILTRE_ETAT_COMPTE.items()},
    )
    compteurs["actuels"] = compteurs["total"] - compteurs["anciens"]
    residents = _filtrer(_residents(), recherche, etage, compte)
    if compte != EtatCompte.DESACTIVE:
        # Les anciens résidents n'apparaissent qu'avec le filtre « Désactivé ».
        residents = residents.exclude(_anciens())
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
            "etats": etats,
            "peut_gerer": peut_gerer,
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
        except IntegrityError:
            # Deux personnes de l'équipe ont choisi la même chambre au même moment.
            formulaire.add_error(
                "chambre", "Cette chambre vient d'être attribuée. Choisissez-en une autre."
            )
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
@permission_required("comptes.voir_residents", raise_exception=True)
def fiche(request, pk):
    resident = get_object_or_404(User.objects.residents(), pk=pk)
    peut_gerer = request.user.has_perm("comptes.gerer_residents")
    if not peut_gerer and est_parti(resident):
        raise Http404  # anciens résidents : réservés à l'accueil et à l'administration
    formulaire = None
    if peut_gerer:
        formulaire, enregistre = _formulaire(request, resident)
        if enregistre:
            messages.success(request, "Les modifications sont enregistrées.")
            return redirect("residents:fiche", pk=resident.pk)
        resident.refresh_from_db()  # le formulaire a pu modifier l'objet sans l'enregistrer
    elif request.method == "POST":
        raise PermissionDenied
    return render(
        request,
        "residents/fiche.html",
        {
            "actif": "residents",
            "formulaire": formulaire,
            "resident": resident,
            "sejour": sejour_en_cours(resident),
            "sejours": resident.sejours.select_related("chambre__etage"),
            "activation": etat_activation(resident),
            "dernier_depart": resident.sejours.filter(depart__isnull=False)
            .order_by("-depart")
            .values_list("depart", flat=True)
            .first(),
        },
    )


@login_required
@permission_required("comptes.gerer_residents", raise_exception=True)
def depart(request, pk):
    """Départ (carte T09) : page de confirmation, car l'action ferme le compte."""
    resident = get_object_or_404(User.objects.residents(), pk=pk)
    if resident.pk == request.user.pk:
        raise PermissionDenied
    if est_parti(resident):
        messages.info(request, "Le départ de cette personne est déjà enregistré.")
        return redirect("residents:fiche", pk=resident.pk)
    sejour = sejour_en_cours(resident)
    formulaire = FormulaireDepart(request.POST or None, sejour=sejour)
    if request.method == "POST" and formulaire.is_valid():
        try:
            enregistrer_depart(resident, formulaire.cleaned_data["depart"], requete=request)
        except ValidationError as erreur:
            if erreur.code == "deja_parti":
                messages.info(request, erreur.messages[0])
                return redirect("residents:fiche", pk=resident.pk)
            formulaire.add_error("depart", erreur.messages)
        else:
            nom = resident.get_full_name() or resident.get_username()
            messages.success(
                request, f"Le départ de {nom} est enregistré. Son compte est désactivé."
            )
            return redirect("residents:fiche", pk=resident.pk)
    return render(
        request,
        "residents/depart.html",
        {"actif": "residents", "resident": resident, "sejour": sejour, "formulaire": formulaire},
    )


@login_required
@permission_required("comptes.gerer_residents", raise_exception=True)
def retour(request, pk):
    """Retour d'un ancien résident : choisir sa chambre, puis lui remettre un code."""
    resident = get_object_or_404(User.objects.residents(), pk=pk)
    if not est_parti(resident):
        return redirect("residents:fiche", pk=resident.pk)
    formulaire = FormulaireRetour(request.POST or None)
    if request.method == "POST" and formulaire.is_valid():
        donnees = formulaire.cleaned_data
        try:
            enregistrer_retour(resident, donnees["chambre"], donnees["arrivee"], requete=request)
        except (ValidationError, IntegrityError) as erreur:
            messages_erreur = getattr(erreur, "messages", ["Cette chambre vient d'être prise."])
            formulaire.add_error(None, messages_erreur)
        else:
            messages.success(
                request,
                "Le retour est enregistré et le compte réactivé. "
                "Générez un code d'activation pour la personne.",
            )
            return redirect("residents:fiche", pk=resident.pk)
    return render(
        request,
        "residents/retour.html",
        {"actif": "residents", "resident": resident, "formulaire": formulaire},
    )


@require_POST
@login_required
@permission_required("comptes.generer_code_activation", raise_exception=True)
def code_activation(request, pk):
    """Génère un code et l'affiche une seule fois, en page imprimable.

    Réponse à un POST, jamais mise en cache : le code ne peut pas être
    réaffiché (on ne garde que son empreinte).
    """
    resident = get_object_or_404(User.objects.residents(), pk=pk)
    if not resident.is_active:
        messages.info(request, "Ce compte est désactivé : enregistrez d'abord le retour.")
        return redirect("residents:fiche", pk=resident.pk)
    code = generer_code(resident, par=request.user, requete=request)
    lien = request.build_absolute_uri(reverse("activation:saisie")) + "#" + code
    qr = segno.make_qr(lien, error="m").svg_inline(
        scale=4, title=f"Code QR pour activer le compte de {resident.get_full_name()}"
    )
    reponse = render(
        request,
        "residents/code_activation.html",
        {
            "actif": "residents",
            "resident": resident,
            "code": code,
            "adresse": request.build_absolute_uri(reverse("activation:saisie")),
            "expire_le": timezone.now() + DUREE_VALIDITE,
            "qr": mark_safe(qr),  # SVG produit par segno à partir de notre propre lien
        },
    )
    add_never_cache_headers(reponse)
    return reponse


# --- Import CSV et Excel (carte T08) ------------------------------------------

CLE_SESSION_IMPORT = "import_residents"
DUREE_APERCU = 60 * 60  # secondes
TITRES_MODELE = ["Prénom", "Nom", "Téléphone", "Chambre", "Arrivée", "E-mail"]


@login_required
@permission_required("comptes.gerer_residents", raise_exception=True)
def import_fichier(request):
    """Étape 1 : envoi du fichier. Il est lu puis oublié : seules les lignes
    analysées restent dans la session, une heure au plus, jusqu'à la confirmation."""
    formulaire = FormulaireImport(request.POST or None, request.FILES or None)
    if request.method == "POST" and formulaire.is_valid():
        fichier = formulaire.cleaned_data["fichier"]
        try:
            lignes = analyser(lire_fichier(fichier))
        except ErreurFichier as erreur:
            formulaire.add_error("fichier", str(erreur))
        else:
            request.session[CLE_SESSION_IMPORT] = {
                # Relie la confirmation à cet aperçu précis (deux onglets, double clic).
                "jeton": secrets.token_urlsafe(32),
                "cree_le": time.time(),
                "fichier": fichier.name[:100],
                "lignes": vers_session(lignes),
            }
            return redirect("residents:import_apercu")
    return render(
        request,
        "residents/import.html",
        {"actif": "residents", "formulaire": formulaire, "en_tetes": EN_TETES},
    )


def _import_en_cours(request):
    donnees = request.session.get(CLE_SESSION_IMPORT)
    if donnees and time.time() - donnees.get("cree_le", 0) > DUREE_APERCU:
        # Les noms et numéros ne restent pas dans la session plus que nécessaire.
        del request.session[CLE_SESSION_IMPORT]
        messages.info(request, "L'aperçu a expiré. Envoyez de nouveau le fichier.")
        return None
    return donnees


def _confirmer(request, import_en_cours, lignes):
    """Crée les fiches. Renvoie la liste créée, ou None avec un message d'erreur."""
    try:
        with transaction.atomic():
            trace = ImportResidents.objects.create(
                jeton=import_en_cours["jeton"],
                importe_par=request.user,
                fichier=import_en_cours["fichier"],
            )
            creees = importer(lignes)
            trace.nombre = len(creees)
            trace.save(update_fields=["nombre"])
    except ValidationError as erreur:
        messages.warning(request, f"Rien n'a été importé. {' '.join(erreur.messages)}")
    except IntegrityError:
        if ImportResidents.objects.filter(jeton=import_en_cours["jeton"]).exists():
            messages.info(request, "Cet import a déjà été fait.")
            del request.session[CLE_SESSION_IMPORT]
            return []
        messages.warning(
            request,
            "Rien n'a été importé : une chambre ou un numéro vient d'être pris. "
            "Vérifiez l'aperçu à jour.",
        )
    else:
        return creees
    return None


def _envoyer_codes(request, residents):
    """Option de l'import : un code d'activation par SMS aux nouveaux qui ont un numéro."""
    adresse = request.build_absolute_uri(reverse("activation:saisie"))
    avec_numero = [r for r in residents if r.telephone]
    envoyes = sum(
        envoyer_code_par_sms(r, adresse, par=request.user, requete=request) for r in avec_numero
    )
    if envoyes:
        s = "s" if envoyes > 1 else ""
        messages.success(request, f"{envoyes} code{s} d'activation envoyé{s} par SMS.")
    if envoyes < len(avec_numero):
        messages.warning(
            request,
            f"{len(avec_numero) - envoyes} SMS n'ont pas pu partir : "
            "remettez ces codes à l'accueil.",
        )
    if len(avec_numero) < len(residents):
        messages.info(
            request,
            f"{len(residents) - len(avec_numero)} résident(s) sans numéro : "
            "code à remettre à l'accueil.",
        )


@login_required
@permission_required("comptes.gerer_residents", raise_exception=True)
def import_apercu(request):
    """Étape 2 : aperçu ligne par ligne, puis import des lignes prêtes."""
    import_en_cours = _import_en_cours(request)
    if not import_en_cours:
        return redirect("residents:import")
    lignes = depuis_session(import_en_cours["lignes"])
    pretes = [ligne.numero for ligne in lignes if ligne.prete]
    situation_changee = autre_apercu = False

    if request.method == "POST":
        if request.POST.get("jeton") != import_en_cours["jeton"]:
            # Cet onglet montrait un autre fichier, remplacé depuis dans la session.
            autre_apercu = True
        elif request.POST.get("action") == "annuler":
            del request.session[CLE_SESSION_IMPORT]
            messages.info(request, "Import annulé. Aucune fiche n'a été créée.")
            return redirect("residents:import")
        elif request.POST.get("pretes", "") != ",".join(map(str, pretes)):
            # Une chambre ou un numéro a été pris depuis l'aperçu.
            situation_changee = True
        else:
            creees = _confirmer(request, import_en_cours, lignes)
            if creees is not None:
                request.session.pop(CLE_SESSION_IMPORT, None)
                if creees:
                    s = "s" if len(creees) > 1 else ""
                    messages.success(request, f"{len(creees)} résident{s} importé{s}.")
                    peut_generer = request.user.has_perm("comptes.generer_code_activation")
                    if request.POST.get("envoyer_codes") == "oui" and peut_generer:
                        _envoyer_codes(request, creees)
                return redirect("residents:liste")
            lignes = depuis_session(import_en_cours["lignes"])
            pretes = [ligne.numero for ligne in lignes if ligne.prete]

    return render(
        request,
        "residents/import.html",
        {
            "actif": "residents",
            "fichier": import_en_cours["fichier"],
            "jeton": import_en_cours["jeton"],
            "lignes": lignes,
            "pretes": ",".join(map(str, pretes)),
            "nombre_pretes": len(pretes),
            "nombre_a_corriger": len(lignes) - len(pretes),
            "situation_changee": situation_changee,
            "autre_apercu": autre_apercu,
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
