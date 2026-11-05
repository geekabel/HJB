"""Import des résidents depuis un fichier CSV ou Excel (.xlsx).

Étapes : lire le fichier, analyser chaque ligne (aperçu), puis créer les
fiches des seules lignes prêtes, dans une transaction.

Bibliothèques :
- csv (Python) : https://docs.python.org/3/library/csv.html
- openpyxl, en lecture seule : https://openpyxl.readthedocs.io/en/3.1/optimized.html
  defusedxml est installé : openpyxl s'en sert contre les attaques XML
  (https://openpyxl.readthedocs.io/en/stable/).
"""

import csv
import io
import unicodedata
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

from comptes.models import User
from comptes.telephone import afficher_telephone, normaliser_telephone
from logement.models import Chambre
from logement.services import affecter_chambre

from .forms import nom_utilisateur_libre

TAILLE_MAX = 2 * 1024 * 1024  # 2 Mo : bien plus qu'une liste de résidents
LIGNES_MAX = 500
LIGNES_BRUTES_MAX = 5000  # lignes lues au plus, vides comprises
TAILLE_DECOMPRESSEE_MAX = 20 * 1024 * 1024  # contre les archives qui « gonflent »
ILLISIBLE_XLSX = "Ce fichier Excel est illisible. Enregistrez-le de nouveau en .xlsx."
COLONNES_MAX = 20
EXTENSIONS = (".csv", ".xlsx")

# Colonne attendue -> en-têtes acceptés (comparés sans accents, espaces ni casse).
EN_TETES = {
    "prenom": ["prenom", "firstname"],
    "nom": ["nom", "nomdefamille", "lastname"],
    "telephone": ["telephone", "tel", "portable", "mobile", "telephoneportable"],
    "chambre": ["chambre", "nchambre", "numerodechambre", "numerochambre"],
    "arrivee": ["arrivee", "datedarrivee", "datearrivee", "entree", "datedentree"],
    "email": ["email", "mail", "courriel", "adresseemail"],
}
OBLIGATOIRES = ("prenom", "nom")
FORMATS_DATE = ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y")


class PointVirgule(csv.excel):
    delimiter = ";"


class ErreurFichier(Exception):
    """Le fichier entier est refusé (format, taille, en-têtes…)."""


def _cle(texte):
    sans_accents = unicodedata.normalize("NFKD", str(texte or "")).encode("ascii", "ignore")
    return "".join(c for c in sans_accents.decode().lower() if c.isalnum())


CLE_PAR_EN_TETE = {variante: cle for cle, variantes in EN_TETES.items() for variante in variantes}


# --- Lecture ---------------------------------------------------------------


def _cellules_csv(contenu):
    """Génère les lignes d'un CSV. Lève ErreurFichier si le texte est illisible."""
    texte = None
    for encodage in ("utf-8-sig", "cp1252"):
        try:
            texte = contenu.decode(encodage)
            break
        except UnicodeDecodeError:
            continue
    if texte is None:
        raise ErreurFichier(
            "Les caractères de ce fichier sont illisibles. Dans Excel, enregistrez-le "
            "en « CSV UTF-8 »."
        )
    try:
        dialecte = csv.Sniffer().sniff(texte[:4096], delimiters=";,\t")
    except csv.Error:
        dialecte = PointVirgule  # une seule colonne : on prend le séparateur d'Excel en français
    # newline="" comme le demande la doc du module csv.
    lecteur = csv.reader(io.StringIO(texte, newline=""), dialecte)
    try:
        for ligne in lecteur:
            yield ligne[:COLONNES_MAX]
    except csv.Error as erreur:
        raise ErreurFichier(
            "Ce fichier CSV est mal formé (guillemets ou cellule trop longue)."
        ) from erreur


def _verifier_archive(fichier):
    """Un .xlsx est une archive zip : on refuse celles qui gonflent trop une fois ouvertes."""
    try:
        with zipfile.ZipFile(fichier) as archive:
            taille = sum(info.file_size for info in archive.infolist())
    except (zipfile.BadZipFile, OSError) as erreur:
        raise ErreurFichier(ILLISIBLE_XLSX) from erreur
    if taille > TAILLE_DECOMPRESSEE_MAX:
        raise ErreurFichier(ILLISIBLE_XLSX)
    fichier.seek(0)


def _cellules_xlsx(fichier):
    """Génère les lignes de la première feuille d'un .xlsx."""
    from openpyxl import load_workbook

    _verifier_archive(fichier)
    try:
        classeur = load_workbook(fichier, read_only=True, data_only=True)
    except Exception as erreur:  # fichier piégé ou abîmé : toute erreur de lecture le refuse
        raise ErreurFichier(ILLISIBLE_XLSX) from erreur
    try:
        feuille = classeur.active
        # Doc openpyxl : certains logiciels écrivent de mauvaises dimensions.
        feuille.reset_dimensions()
        for ligne in feuille.iter_rows(max_col=COLONNES_MAX, values_only=True):
            yield list(ligne)
    except Exception as erreur:
        raise ErreurFichier(ILLISIBLE_XLSX) from erreur
    finally:
        classeur.close()  # obligatoire en lecture seule


def _sans_cellules_vides_a_la_fin(ligne):
    ligne = list(ligne)
    while ligne and str(ligne[-1] if ligne[-1] is not None else "").strip() == "":
        ligne.pop()
    return ligne


def lire_fichier(fichier):
    """Renvoie les lignes non vides du fichier, en-tête comprise : [(numéro, cellules)…].

    Le numéro est celui de la ligne dans le fichier, lignes vides comprises,
    pour que l'aperçu renvoie à la bonne ligne.
    """
    nom = (fichier.name or "").lower()
    if nom.endswith(".xls"):
        raise ErreurFichier(
            "L'ancien format Excel (.xls) n'est pas pris en charge. "
            "Dans Excel : Fichier, Enregistrer sous, puis « Classeur Excel (.xlsx) »."
        )
    if not nom.endswith(EXTENSIONS):
        raise ErreurFichier("Le fichier doit être un .csv ou un .xlsx.")
    if fichier.size > TAILLE_MAX:
        raise ErreurFichier("Le fichier dépasse 2 Mo. Une liste de résidents est bien plus petite.")
    cellules = _cellules_csv(fichier.read()) if nom.endswith(".csv") else _cellules_xlsx(fichier)
    trop_long = f"Le fichier dépasse {LIGNES_MAX} lignes. Découpez-le en plusieurs fichiers."
    lignes = []
    try:
        for numero, brut in enumerate(cellules, start=1):
            if numero > LIGNES_BRUTES_MAX:
                raise ErreurFichier(trop_long)
            ligne = _sans_cellules_vides_a_la_fin(brut)
            if ligne:
                lignes.append((numero, ligne))
                if len(lignes) > LIGNES_MAX + 1:  # + 1 : la ligne des titres
                    raise ErreurFichier(trop_long)
    finally:
        cellules.close()
    if not lignes:
        raise ErreurFichier("Le fichier est vide.")
    return lignes


# --- Analyse ---------------------------------------------------------------


@dataclass
class LigneImport:
    numero: int  # numéro de ligne dans le fichier (l'en-tête est la ligne 1)
    prenom: str = ""
    nom: str = ""
    telephone: str = ""  # E.164 si valide, sinon la saisie
    chambre: str = ""
    arrivee: str = ""  # AAAA-MM-JJ si valide, sinon la saisie
    # Chambre sans date : arrivée le jour de l'import (pas le jour de l'aperçu).
    arrivee_auto: bool = False
    email: str = ""
    # Erreurs de lecture (date illisible) : gardées entre l'aperçu et la confirmation.
    erreurs_forme: list = field(default_factory=list)
    # Calculés par _verifier(), à chaque analyse.
    erreurs: list = field(default_factory=list)
    avertissements: list = field(default_factory=list)
    telephone_valide: bool = False

    @property
    def prete(self):
        return not self.erreurs

    @property
    def nom_complet(self):
        return f"{self.prenom} {self.nom}".strip()

    @property
    def telephone_affiche(self):
        return afficher_telephone(self.telephone) if self.telephone_valide else self.telephone

    @property
    def date_arrivee(self):
        if self.arrivee_auto:
            return timezone.localdate()
        try:
            return date.fromisoformat(self.arrivee)
        except ValueError:
            return None


def _texte(valeur):
    if valeur is None:
        return ""
    if isinstance(valeur, float) and valeur.is_integer():
        valeur = int(valeur)
    return str(valeur).strip()


def _telephone_brut(valeur):
    texte = _texte(valeur)
    # Excel efface le 0 initial d'un numéro saisi comme un nombre : 612345678.
    if isinstance(valeur, int | float) and len(texte) == 9 and texte[0] in "67":
        texte = "0" + texte
    return texte


def _date(valeur):
    if isinstance(valeur, datetime):
        return valeur.date()
    if isinstance(valeur, date):
        return valeur
    texte = _texte(valeur)
    for format_date in FORMATS_DATE:
        try:
            return datetime.strptime(texte, format_date).date()
        except ValueError:
            continue
    return None


def _colonnes(en_tete):
    colonnes = {}
    for index, titre in enumerate(en_tete):
        cle = CLE_PAR_EN_TETE.get(_cle(titre))
        if cle and cle not in colonnes:
            colonnes[cle] = index
    manquantes = [cle for cle in OBLIGATOIRES if cle not in colonnes]
    if manquantes:
        noms = " et ".join(f"« {EN_TETES[c][0].capitalize()} »" for c in manquantes)
        raise ErreurFichier(
            f"La première ligne doit contenir les titres des colonnes. Il manque {noms}."
        )
    return colonnes


def analyser(lignes):
    """Analyse les lignes lues par lire_fichier(). Renvoie une liste de LigneImport."""
    colonnes = _colonnes(lignes[0][1])
    resultat = []
    for numero, cellules in lignes[1:]:

        def valeur(cle, cellules=cellules):
            index = colonnes.get(cle)
            return cellules[index] if index is not None and index < len(cellules) else None

        ligne = LigneImport(
            numero=numero,
            prenom=_texte(valeur("prenom")),
            nom=_texte(valeur("nom")),
            telephone=_telephone_brut(valeur("telephone")),
            chambre=_texte(valeur("chambre")).upper(),
            email=_texte(valeur("email")),
        )
        brut_arrivee = valeur("arrivee")
        if _texte(brut_arrivee):
            jour = _date(brut_arrivee)
            ligne.arrivee = jour.isoformat() if jour else _texte(brut_arrivee)
            if jour is None:
                ligne.erreurs_forme.append(
                    f"« {ligne.arrivee} » n'est pas une date. Écrivez-la comme 01/09/2026."
                )
        elif ligne.chambre:
            ligne.arrivee_auto = True
        resultat.append(ligne)
    _verifier(resultat)
    return resultat


def _verifier(lignes):
    """Calcule les erreurs de chaque ligne : champs, doublons dans le fichier et en base.

    Quelques requêtes en tout, quel que soit le nombre de lignes.
    """
    for ligne in lignes:
        ligne.erreurs = list(ligne.erreurs_forme)
        ligne.avertissements = []
        ligne.telephone_valide = False
        if ligne.telephone:
            try:
                ligne.telephone = normaliser_telephone(ligne.telephone)
                ligne.telephone_valide = True
            except ValidationError as erreur:
                ligne.erreurs.append(f"Numéro « {ligne.telephone} » : {erreur.messages[0]}")

    numeros = {lg.telephone for lg in lignes if lg.telephone_valide}
    deja_pris = {u.telephone: u for u in User.objects.filter(telephone__in=numeros)}
    chambres = {
        c.numero: c
        for c in Chambre.objects.filter(numero__in={lg.chambre for lg in lignes if lg.chambre})
        .select_related("etage")
        .prefetch_related("sejours__resident")
    }
    noms_existants = {
        (prenom.casefold(), nom.casefold())
        for prenom, nom in User.objects.values_list("first_name", "last_name")
    }
    numeros_vus, chambres_vues = {}, {}

    for ligne in lignes:
        if not ligne.prenom:
            ligne.erreurs.append("Le prénom manque.")
        if not ligne.nom:
            ligne.erreurs.append("Le nom manque.")
        if ligne.email:
            try:
                validate_email(ligne.email)
            except ValidationError:
                ligne.erreurs.append(f"« {ligne.email} » n'est pas une adresse e-mail.")

        if ligne.telephone_valide:
            if ligne.telephone in numeros_vus:
                ligne.erreurs.append(f"Même numéro que la ligne {numeros_vus[ligne.telephone]}.")
            else:
                numeros_vus[ligne.telephone] = ligne.numero
                if ligne.telephone in deja_pris:
                    deja = deja_pris[ligne.telephone]
                    ligne.erreurs.append(
                        f"Ce numéro est déjà celui de {deja.get_full_name() or deja}."
                    )

        if ligne.chambre:
            chambre = chambres.get(ligne.chambre)
            if chambre is None:
                ligne.erreurs.append(f"La chambre {ligne.chambre} n'existe pas.")
            elif not chambre.active:
                ligne.erreurs.append(f"La chambre {ligne.chambre} est fermée.")
            elif ligne.chambre in chambres_vues:
                ligne.erreurs.append(f"Même chambre que la ligne {chambres_vues[ligne.chambre]}.")
            else:
                chambres_vues[ligne.chambre] = ligne.numero
                sejours = chambre.sejours.all()
                occupant = next((s.resident for s in sejours if s.en_cours), None)
                jour = ligne.date_arrivee
                # Un séjour terminé après la date d'arrivée voulue croise le nouveau.
                fin = max(
                    (s.depart for s in sejours if s.depart and jour and s.depart > jour),
                    default=None,
                )
                if occupant:
                    ligne.erreurs.append(
                        f"La chambre {ligne.chambre} est déjà occupée par "
                        f"{occupant.get_full_name() or occupant}."
                    )
                elif fin:
                    ligne.erreurs.append(
                        f"La chambre {ligne.chambre} était occupée jusqu'au "
                        f"{fin:%d/%m/%Y} : l'arrivée doit être à partir de cette date."
                    )

        if (ligne.prenom.casefold(), ligne.nom.casefold()) in noms_existants:
            ligne.avertissements.append(
                "Une fiche existe déjà à ce nom. Vérifiez que ce n'est pas la même personne."
            )


# --- Conservation entre l'aperçu et la confirmation -------------------------


def vers_session(lignes):
    return [asdict(ligne) for ligne in lignes]


def depuis_session(donnees):
    """Reconstruit les lignes et les vérifie de nouveau : la base a pu changer."""
    lignes = [LigneImport(**d) for d in donnees]
    _verifier(lignes)
    return lignes


# --- Import ------------------------------------------------------------------


@transaction.atomic
def importer(lignes):
    """Crée une fiche (et un séjour) par ligne prête. Tout ou rien.

    Renvoie la liste des fiches créées. Lève ValidationError si une ligne est
    refusée au dernier moment ; rien n'est alors enregistré.
    """
    chambres = {
        c.numero: c for c in Chambre.objects.filter(numero__in=[lg.chambre for lg in lignes])
    }
    creees = []
    for ligne in lignes:
        if not ligne.prete:
            continue
        try:
            creees.append(_creer(ligne, chambres))
        except ValidationError as erreur:
            raise ValidationError(f"Ligne {ligne.numero} : {' '.join(erreur.messages)}") from erreur
    return creees


def _creer(ligne, chambres):
    resident = User(
        username=nom_utilisateur_libre(ligne.prenom, ligne.nom),
        first_name=ligne.prenom,
        last_name=ligne.nom,
        telephone=ligne.telephone,
        email=ligne.email,
    )
    resident.set_unusable_password()
    resident.full_clean(exclude=["password"])
    resident.save()
    if ligne.chambre:
        affecter_chambre(resident, chambres[ligne.chambre], ligne.date_arrivee)
    return resident
