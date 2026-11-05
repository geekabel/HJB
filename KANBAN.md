# Kanban du projet HJB Résidence

Dernière mise à jour : 5 novembre 2026

Ce fichier suit toutes les tâches jusqu'à la mise en service. Après chaque tâche, on déplace sa carte dans « Fait » et on coche ses critères.

- Maquettes UI/UX : canevas « HJB Résidence · maquettes » (12 écrans)
- Tableau visuel : artifact « Kanban HJB Résidence », mis à jour en même temps que ce fichier
- Modèle de données : [docs/modele-de-donnees.md](docs/modele-de-donnees.md)
- Glossaire du code : [docs/glossaire.md](docs/glossaire.md). Depuis T14b, le code est en anglais ; les cartes plus anciennes citent les anciens noms français.

## Règles de travail

**Branches**
1. `main` contient ce qui est en production. `develop` contient le travail validé.
2. Chaque tâche se fait sur une branche locale `feat/tXX-nom-court`, créée depuis `develop`.
3. Quand la tâche est finie et testée, on la fusionne dans `develop` avec `git merge --no-ff`.

**Commits** : spécification [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/#specification).
- Forme : `type(portée facultative): description`, puis un corps et des pieds de page facultatifs.
- Types utilisés : `feat`, `fix`, `docs`, `test`, `refactor`, `style`, `build`, `ci`, `chore`, `perf`.
- Changement incompatible : `!` avant les deux-points, ou un pied de page `BREAKING CHANGE: ...`.

**Dépôt public : aucune donnée sensible**
- Jamais de secret dans le dépôt : clés, mots de passe, jetons d'API, clés VAPID, clé de chiffrement du wifi. Ils vivent dans l'environnement du serveur (`.env`, ignoré par Git).
- Jamais de vraies données de la résidence : noms, téléphones, numéros de chambre réels, codes wifi. Les tests et les exemples utilisent des données inventées.
- Pas d'adresse e-mail ni de numéro de téléphone personnels dans les fichiers.
- La CI recherche les secrets à chaque push (carte T02).

**Sources de vérité**
1. Django : uniquement la [documentation officielle](https://docs.djangoproject.com/en/6.1/), pour la version utilisée.
2. Chaque bibliothèque : lire sa documentation officielle avant de l'utiliser.
3. Si un problème reste bloquant après la doc : tickets GitHub du projet, puis forums (Django Forum, Stack Overflow).
4. HTML, CSS et JavaScript : [MDN](https://developer.mozilla.org/fr/).

**Définition de « fait » (pour toutes les cartes)**
- Le code suit la documentation officielle citée dans la carte.
- Les tests passent (`python manage.py test`).
- `python manage.py check` ne signale rien.
- Tout HTML et CSS produit passe les validateurs du W3C (HTML : [Nu Html Checker](https://validator.w3.org/nu/), CSS : [validateur CSS](https://jigsaw.w3.org/css-validator/)).
- Le code front est moderne : HTML sémantique, CSS natif (variables, grilles, `:focus-visible`, `prefers-color-scheme`), JavaScript sans dépendance quand c'est possible.
- Accessibilité : contraste du texte au moins 4,5:1, bordures des contrôles au moins 3:1, zones cliquables d'au moins 44 px, navigation au clavier.
- Ce fichier et le modèle de données sont à jour.

## Choix techniques

| Sujet | Choix | Pourquoi |
|---|---|---|
| Langage | Python 3.13 | Supporté par Django 6.1 (3.12 à 3.15) |
| Framework | Django 6.1 | Dernière version, support jusqu'en décembre 2027. Passage à 6.2 LTS (avril 2027) prévu en fin de projet |
| Base de données | SQLite en développement, PostgreSQL en production | Django 6.1 demande SQLite 3.37 ou plus et PostgreSQL 15 ou plus |
| Tâches en arrière-plan | Framework de tâches de Django + django-tasks-db (choisi en T21) | File d'attente dans la base, *worker* `db_worker`. Les backends livrés avec Django servent au développement et aux tests |
| Notifications | Web Push (application web installable, PWA) | Gratuit. Le SMS ne sert que de secours |
| SMS | Couche « fournisseur » interchangeable | Console en développement, SMSGate pour les tests réels, OVHcloud ou Brevo en production |
| Connexion | Code d'activation remis à l'accueil, code SMS, puis clé d'accès (passkey) | Le numéro de chambre n'est pas un secret |
| Front | Gabarits Django, CSS natif, JavaScript léger | Moins de dépendances, validation W3C plus simple |
| Import Excel | openpyxl en lecture seule, avec defusedxml | Lit les .xlsx sans Excel ; defusedxml bloque les fichiers XML piégés |
| API OVHcloud | Bibliothèque officielle python-ovh | Conseillée par OVHcloud : elle signe les requêtes ; pas de cryptographie maison |
| Code QR | segno (pur Python, sans dépendance, BSD) | SVG inséré dans la page, imprimable |
| Clés d'accès | django-otp-webauthn 0.10.3 (py_webauthn), script maison | Cryptographie confiée à py_webauthn ; script en français, sans `alert()` |

## Tableau

### En cours

| ID | Tâche | Épopée |
|---|---|---|
| | *(vide)* | |

### À faire

| ID | Tâche | Épopée | Dépend de |
|---|---|---|---|
| T22 | Réponse Présent ou Absent | E4 Messages | T21 |
| T23 | Boîte de réception du résident | E4 Messages | T21 |
| T24 | Statuts de livraison des SMS | E4 Messages | T21 |
| T25 | Sondages anonymes | E5 Votes | T21 |
| T26 | Disponibilités des éducateurs | E6 Rendez-vous | T04 |
| T27 | Réservation d'un rendez-vous | E6 Rendez-vous | T26, T13 |
| T28 | Messages directs avec un éducateur | E6 Rendez-vous | T13 |
| T29 | Rappels et annulation de rendez-vous | E6 Rendez-vous | T27, T19 |
| T30 | Signaler un problème | E7 Signalements | T13 |
| T31 | Tableau des signalements (équipe) | E7 Signalements | T30 |
| T32 | Délais, relances et récapitulatif quotidien | E7 Signalements | T31, T21 |
| T33 | Suivi et confirmation par le résident | E7 Signalements | T31 |
| T34 | Accueil du résident | E8 Accueils | T23, T27, T33 |
| T35 | Tableau de bord de l'équipe | E8 Accueils | T21, T31, T27 |
| T36 | RGPD | E9 Mise en service | T09, T15 |
| T37 | Sécurité avant la mise en ligne | E9 Mise en service | toutes |
| T38 | Déploiement | E9 Mise en service | T37 |
| T39 | Essai pilote sur un étage | E9 Mise en service | T38 |
| T40 | Guides d'utilisation | E9 Mise en service | T39 |
| T41 | Discussion entre résidents et modération | E10 Phase 2 | T39 |

### Fait

| ID | Tâche | Terminé le |
|---|---|---|
| R01 | Recherche : envoi de SMS, options gratuites, cadre légal | 21 oct. 2026 |
| R02 | Choix d'architecture : application web, Django, fournisseur SMS interchangeable | 4 nov. 2026 |
| R03 | Maquettes UI/UX (7 écrans résident, 5 écrans équipe) et palette du logo | 4 nov. 2026 |
| R04 | Kanban et modèle de données | 4 nov. 2026 |
| T01 | Initialiser le projet Django | 5 nov. 2026 |
| T02 | Outils qualité et intégration continue | 5 nov. 2026 |
| T03 | Gabarits de base et système de design CSS | 5 nov. 2026 |
| T04 | Rôles et permissions | 5 nov. 2026 |
| T05 | Journal d'audit | 5 nov. 2026 |
| T06 | Étages, chambres et séjours | 5 nov. 2026 |
| T07 | Liste et fiche des résidents (équipe) | 5 nov. 2026 |
| T08 | Import CSV et Excel des résidents | 5 nov. 2026 |
| T09 | Départ d'un résident | 5 nov. 2026 |
| T10 | Couche fournisseur SMS | 5 nov. 2026 |
| T11 | Code d'activation | 5 nov. 2026 |
| T12 | Vérification du téléphone par code SMS | 5 nov. 2026 |
| T13 | Connexion par clé d'accès (passkey) | 5 nov. 2026 |
| T14 | Sécurité de l'espace équipe | 5 nov. 2026 |
| T14b | Code en anglais | 5 nov. 2026 |
| T15 | Accès wifi chiffré (équipe) | 5 nov. 2026 |
| T15b | Format du portail wifi et import de la liste | 5 nov. 2026 |
| T16 | Écran « Mon wifi » du résident | 5 nov. 2026 |
| T18 | Application installable (PWA) | 5 nov. 2026 |
| T19 | Notifications Web Push | 5 nov. 2026 |
| T17 | Rappels d'expiration du wifi | 5 nov. 2026 |
| T20 | Modèles de message et composeur | 5 nov. 2026 |
| T21 | Envoi programmé et relances | 5 nov. 2026 |

## Détail des cartes

### E0 Fondations

#### T01 Initialiser le projet Django (fait le 5 nov. 2026)
- **But** : un projet Django 6.1 qui démarre, avec le modèle utilisateur personnalisé créé avant la première migration.
- **Docs** : [tutoriel partie 1](https://docs.djangoproject.com/en/6.1/intro/tutorial01/), [modèle utilisateur personnalisé](https://docs.djangoproject.com/en/6.1/topics/auth/customizing/#using-a-custom-user-model-when-starting-a-project), [réglages](https://docs.djangoproject.com/en/6.1/topics/settings/), [liste de contrôle du déploiement](https://docs.djangoproject.com/en/6.1/howto/deployment/checklist/), [réglage `MAILERS`](https://docs.djangoproject.com/en/6.1/ref/settings/#mailers).
- [x] Dépendances épinglées (`requirements.txt`, `requirements-dev.txt`) : Django 6.1.3, Ruff 0.17.3
- [x] Projet `config` avec réglages séparés : `base`, `dev`, `prod`
- [x] `SECRET_KEY` lue depuis une variable d'environnement en production (refus de démarrer sans elle, testé)
- [x] Application `comptes` avec `User(AbstractUser)` et `AUTH_USER_MODEL`, migration `0001_initial`
- [x] Langue française, fuseau `Europe/Paris`, `USE_TZ = True`
- [x] 6 tests verts, `check` propre, `makemigrations --check` propre
- [x] `check --deploy` sans erreur. Restent volontairement `security.W005` et `security.W021` (HSTS sur les sous-domaines et préchargement) : ils dépendent du domaine final et seront réglés en T37
- [x] README : installation en local, tests, réglages
- **Notes** : en production, l'e-mail passe par SMTP (réglage `MAILERS`, nouveau en 6.1), sinon `check --deploy` refuse le backend console. La configuration de Ruff est faite en T02.

#### T02 Outils qualité et intégration continue (fait le 5 nov. 2026)
- **But** : chaque push vérifie le code automatiquement.
- **Docs** : [configuration de Ruff](https://docs.astral.sh/ruff/configuration/), [setup-python](https://github.com/actions/setup-python), [setup-java](https://github.com/actions/setup-java), [Nu Html Checker](https://validator.github.io/validator/docs/vnu.1.html), [gitleaks-action](https://github.com/gitleaks/gitleaks-action).
- [x] Ruff 0.17.3 configuré dans `pyproject.toml` (règles E, W, F, I, B, UP, DJ, RUF ; lignes de 100)
- [x] GitHub Actions : Ruff, `check`, `check --deploy` (clé jetable générée à chaque passage), `makemigrations --check`, tests
- [x] Validation W3C automatique : les tests enregistrent les pages (`HTML_CAPTURE_DIR`), puis `outils.valider_w3c` passe ces pages et tous les CSS du projet au Nu Html Checker (vnu-jar 26.10.12, Java 21). Vérifié en local : une page fautive fait échouer, une page correcte passe
- [x] Recherche de secrets à chaque push avec gitleaks (compte personnel : pas de licence)
- [x] Les deux workflows sont verts sur GitHub
- **Notes** : pas encore de page à nous, donc la validation HTML n'a rien à vérifier. Elle prendra effet dès T03 : chaque test qui rend une page doit appeler `enregistrer_page`. La clé de développement porte un commentaire `gitleaks:allow`, car c'est une valeur publique et volontaire. À partir de T02, les commits utilisent l'adresse anonyme de GitHub.

#### T03 Gabarits de base et système de design CSS (fait le 5 nov. 2026)
- **But** : reproduire le style des maquettes une seule fois, en composants réutilisables.
- **Docs** : [langage de gabarits (héritage)](https://docs.djangoproject.com/en/6.0/ref/templates/language/), [balises personnalisées](https://docs.djangoproject.com/en/6.1/howto/custom-template-tags/), [fichiers statiques](https://docs.djangoproject.com/en/6.1/howto/static-files/), MDN ([`:focus-visible`](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Selectors/:focus-visible), [`<meta name="color-scheme">`](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/meta/name/color-scheme)).
- [x] Jetons de couleur du logo : bleu `#03a9f4`, vert `#8bc34a`, jaune `#ffc107`, bleu nuit `#06202f`, bleu d'action `#006fa3`
- [x] Sens des couleurs : bleu = action et information, jaune = attention, vert = terminé
- [x] Polices : Bricolage Grotesque (titres) et Atkinson Hyperlegible (texte), servies depuis le site avec leurs licences OFL
- [x] Composants : boutons, puces, cartes, champs, choix, badges de statut, bandeaux, compteurs, barre de navigation mobile, menu latéral de l'équipe
- [x] Mode sombre et contour de focus visible. Toutes les paires de couleurs passent : texte 4,5:1, contrôles et focus 3:1, dans les deux thèmes
- [x] Gabarit résident (mobile d'abord) et gabarit équipe (ordinateur, qui se replie sur téléphone)
- [x] Pages modèles validées W3C : guide de style et accueil résident d'exemple (`/guide/`, réservé à l'équipe), plus la feuille de style
- [x] Rendu vérifié dans Chrome : mobile 390 px et ordinateur 1280 px, thèmes clair et sombre, aucun débordement, polices chargées, lien d'évitement au premier Tab
- **Notes** : le validateur W3C n'accepte pas encore `@container`, donc on ne l'utilise pas. Les liens de la navigation pointent vers « # » jusqu'à ce que leurs pages existent. Une chaîne écrite en dur dans un gabarit n'est pas échappée par Django : seules les variables le sont, ce que vérifie un test.

#### T04 Rôles et permissions (fait le 5 nov. 2026)
- **Docs** : [permissions et autorisation](https://docs.djangoproject.com/en/6.1/topics/auth/default/#permissions-and-authorization), [signal `post_migrate`](https://docs.djangoproject.com/en/6.1/ref/signals/#post-migrate), [RunPython](https://docs.djangoproject.com/en/6.1/ref/migration-operations/#runpython), [phonenumbers](https://github.com/daviddrysdale/python-phonenumbers).
- [x] Rôles : Accueil, Éducateur, Maintenance, Administration, Modérateur. **Une personne peut en avoir plusieurs** (ajout du 5 nov.) : un rôle est un groupe Django, les droits se cumulent. Aucun rôle du personnel : résident
- [x] Groupes et permissions créés au `migrate`, par un gestionnaire `post_migrate` (voir la note)
- [x] Champ `telephone` (portable, E.164, unique s'il est renseigné)
- [x] Tests d'accès par rôle : chaque rôle a exactement ses droits, cumul de plusieurs rôles, modérateur résident, cases à cocher de l'administration
- [x] Migration `0003` : les anciens rôles (champ unique) sont recopiés dans les groupes avant la suppression du champ. Vérifié sur une base à l'état `0002`
- [x] Guide de style réservé aux rôles du personnel : un résident connecté reçoit un 403
- **Notes** : la carte prévoyait une migration de données. La doc de Django indique que les permissions sont créées par le signal `post_migrate`, donc après les migrations : sur une base neuve, une migration ne pourrait pas les attribuer. Les groupes sont donc créés dans ce même signal, à chaque `migrate`, et le code de `comptes/roles.py` fait foi. Le numéro est normalisé dans `clean_fields()`, avant les validateurs, car `full_clean()` les lance avant `clean()`. Connexion provisoire par la page de l'administration jusqu'à T13 : elle n'accepte que les comptes `is_staff`. Table des droits dans [docs/modele-de-donnees.md](docs/modele-de-donnees.md#rôles-groupes-et-permissions).

#### T05 Journal d'audit (fait le 5 nov. 2026)
- **Docs** : [GenericForeignKey](https://docs.djangoproject.com/en/6.1/ref/contrib/contenttypes/#generic-relations), [JSONField](https://docs.djangoproject.com/en/6.1/ref/models/fields/#jsonfield), [`HttpRequest.META`](https://docs.djangoproject.com/en/6.1/ref/request-response/#django.http.HttpRequest.META), [pagination](https://docs.djangoproject.com/en/6.1/topics/pagination/), [MDN : formats de date et d'heure](https://developer.mozilla.org/en-US/docs/Web/HTML/Guides/Date_and_time_formats).
- [x] Modèle `EntreeJournal` et fonction `journaliser(action, *, acteur, cible, details, requete)` (application `journal`)
- [x] Une entrée ne peut être ni modifiée ni supprimée : le modèle refuse, l'administration est en lecture seule
- [x] Branché sur le changement de rôles (administration). Les trois autres actions sont prêtes et seront branchées par leurs cartes : code d'activation (T11), affichage d'un code wifi (T15), départ d'un résident (T09)
- [x] Page `/equipe/journal/` réservée à la permission `voir_journal` (Administration) : filtre par action, 50 entrées par page. Lien dans le menu de l'équipe, qui affiche aussi les rôles de la personne
- [x] Validé W3C, rendu vérifié dans Chrome (mobile et ordinateur, clair et sombre). Sur mobile, le tableau défile et sa zone est atteignable au clavier
- **Notes** : l'entrée garde le nom de l'acteur et un libellé de la cible, pour rester lisible si le compte est supprimé. L'adresse IP vient de `REMOTE_ADDR` seulement : `X-Forwarded-For` peut être inventé par le client, le réglage derrière un proxy est prévu en T38. Le format `c` du filtre `date` ajoute des microsecondes, que le validateur refuse dans `datetime` : on écrit la date sans elles.

### E1 Résidents

#### T06 Étages, chambres et séjours (fait le 5 nov. 2026)
- **Docs** : [contraintes](https://docs.djangoproject.com/en/6.1/ref/models/constraints/), [validation des modèles](https://docs.djangoproject.com/en/6.1/ref/models/instances/#validating-objects), [Exists et OuterRef](https://docs.djangoproject.com/en/6.1/ref/models/expressions/#exists-subqueries), [inlines de l'administration](https://docs.djangoproject.com/en/6.1/ref/contrib/admin/#inlinemodeladmin-objects).
- [x] Modèles `Etage`, `Chambre`, `Sejour` (application `logement`) et contraintes uniques conditionnelles : un séjour en cours par chambre et par personne, départ jamais avant l'arrivée
- [x] Validation en plus des contraintes : pas de chevauchement de dates (le jour de relève est permis), pas de nouveau séjour dans une chambre fermée
- [x] `affecter_chambre()` : arrivée, déménagement interne (le séjour précédent se termine le jour même) ou correction le jour de l'arrivée, dans une transaction
- [x] Administration Django pour la saisie initiale : un étage et ses chambres sur une seule page, filtre « libre / occupée »
- [x] Tests des contraintes en base et des messages de validation (21 tests)
- **Notes** : un compte qui a des séjours ne peut pas être supprimé (`PROTECT`) : l'historique reste. Le départ d'un résident sera fait en T09.
- **Revue indépendante (5 nov.)** : le filtre « occupée » de l'administration montrait aussi les chambres fermées et vides. Corrigé avec `Exists`.

#### T07 Liste et fiche des résidents (équipe) (fait le 5 nov. 2026)
- **Maquette** : P5.
- **Docs** : [gabarits de groupe de champ](https://docs.djangoproject.com/en/6.1/topics/forms/#reusable-field-group-templates), [moteurs de rendu des formulaires](https://docs.djangoproject.com/en/6.1/ref/forms/renderers/), [aria-describedby des erreurs (5.2)](https://docs.djangoproject.com/en/6.1/releases/5.2/), [messages](https://docs.djangoproject.com/en/6.1/ref/contrib/messages/#message-tags), [Prefetch](https://docs.djangoproject.com/en/6.1/ref/models/querysets/#prefetch-objects).
- [x] Liste `/equipe/residents/` : recherche par nom ou numéro de chambre, filtres par étage (ou « sans chambre ») et par état du compte, 50 par page, filtres gardés d'une page à l'autre
- [x] Compteurs en tête de liste : résidents, comptes activés, pas encore activés
- [x] Numéros masqués dans la liste (« 06 •• •• •• 47 »), avec un texte lisible par les lecteurs d'écran ; complets sur la fiche
- [x] Création et modification d'une fiche, avec chambre et date d'arrivée. Un déménagement interne ferme l'ancien séjour et en ouvre un nouveau
- [x] Consultation avec `voir_residents` (Accueil, Éducateurs, Administration) ; création, modification et import avec `gerer_residents` (Accueil, Administration). Les éducateurs voient une fiche en lecture seule (ajout du 5 nov., à la demande de Godwin)
- [x] Gabarit de champ commun à tous les formulaires (`interface/formulaires`) : libellé, aide, erreurs reliées au champ, mention « facultatif »
- [x] Gabarits validés W3C ; rendu vérifié dans Chrome (mobile et ordinateur, clair et sombre), y compris les erreurs de saisie
- **Notes** : l'état du compte vient pour l'instant de la première connexion (« Activé » ou « Pas encore activé ») ; T11 ajoutera l'invitation et son expiration. La colonne wifi de la maquette arrivera avec T15. Le compte d'un résident n'a pas de mot de passe utilisable : il se connectera par clé d'accès (T13). Correctif général : dans un tableau qui défile, les textes « visuellement cachés » élargissaient la page sur mobile ; le cadre du tableau les contient maintenant. Nombre de requêtes de la liste constant, quel que soit le nombre de résidents (testé).
- **Revue indépendante (5 nov.)** : changer de chambre sans changer la date effaçait l'ancienne chambre de l'historique. La fiche demande maintenant la date du déménagement (sauf correction le jour de l'arrivée). Deux personnes qui donnent la même chambre au même moment : message clair au lieu d'une erreur 500.

#### T08 Import CSV et Excel des résidents (fait le 5 nov. 2026)
- **Docs** : [module `csv` de Python](https://docs.python.org/3/library/csv.html), [openpyxl, mode lecture seule](https://openpyxl.readthedocs.io/en/3.1/optimized.html), [openpyxl et defusedxml](https://openpyxl.readthedocs.io/en/stable/), [phonenumbers](https://github.com/daviddrysdale/python-phonenumbers).
- [x] Envoi du fichier (.csv ou .xlsx, 2 Mo et 500 lignes au plus), aperçu ligne par ligne, erreurs expliquées en clair (numéro, chambre prise ou fermée, doublons dans le fichier, date, e-mail)
- [x] Titres de colonnes souples (accents, majuscules, ordre libre) et modèle CSV à télécharger
- [x] Numéros normalisés au format international, y compris un 0 perdu par Excel (612345678)
- [x] Import des seules lignes prêtes, dans une transaction (tout ou rien)
- [x] Si la base change entre l'aperçu et la confirmation (chambre prise…), rien n'est importé et l'aperçu à jour s'affiche
- [ ] Option « envoyer un code d'activation aux nouveaux » : déplacée en T11, car elle demande le code d'activation et l'envoi de SMS (T10)
- **Notes** : le fichier n'est jamais enregistré ; seules les lignes analysées restent dans la session jusqu'à la confirmation ou l'annulation. openpyxl lit en mode lecture seule, et `defusedxml` est installé, comme le conseille sa doc contre les attaques XML. Le numéro de ligne affiché est celui du fichier, même s'il contient des lignes vides. Une fiche au même nom qu'une fiche existante est signalée sans bloquer. Fichiers d'essai : données inventées uniquement.
- **Revue indépendante (5 nov.)** : corrigé après relecture. Fichiers abîmés ou piégés (encodage, CSV mal formé, XML cassé, archive qui gonfle) refusés avec un message au lieu d'une erreur 500. Les lignes vides ne font plus perdre de lignes. La confirmation est liée à son aperçu par un jeton : deux onglets ou un double clic ne créent rien en double (trace `ImportResidents`, jeton unique en base). Aperçu valable une heure. Un ancien séjour qui croise la date d'arrivée est signalé dans l'aperçu. Une arrivée sans date prend le jour de l'import. 45 tests pour l'import.

#### T09 Départ d'un résident (fait le 5 nov. 2026)
- **Docs** : [signaux](https://docs.djangoproject.com/en/6.1/topics/signals/#defining-and-sending-signals), [sessions en base](https://docs.djangoproject.com/en/6.1/topics/http/sessions/#using-database-backed-sessions), [ModelBackend et comptes inactifs](https://docs.djangoproject.com/en/6.1/ref/contrib/auth/#django.contrib.auth.backends.ModelBackend).
- [x] Fin du séjour (la chambre redevient libre), compte désactivé, sessions fermées sur tous les appareils, le tout dans une transaction
- [x] Page de confirmation qui dit ce qui va se passer, bouton rouge, date du jour ou passée (jamais avant l'arrivée)
- [x] Trace dans le journal d'audit (chambre, date, nombre de sessions fermées) ; le journal nomme maintenant la personne (« Awa Koné (awa.kone) »)
- [x] Liste : les anciens résidents sont à part, derrière le lien « N anciens résidents »
- [x] Fiche d'un ancien résident : identité modifiable, pas de relogement depuis la fiche
- [x] Accès wifi désactivé : fait en T15, branché sur le signal du départ
- **Notes** : le signal `depart_enregistre` est envoyé dans la transaction du départ : si la coupure du wifi (T15) ou des clés d'accès (T13) échoue, rien n'est enregistré (testé). Le mot de passe inutilisable est renouvelé, ce qui invalide aussi toute session restante. Le départ prévu à l'avance (« Départ le 30 nov. » de la maquette) demande une tâche quotidienne : ajouté à T21. Le retour d'un ancien résident : ajouté à T11.
- **Revue indépendante (5 nov.)** : corrigé après relecture. Verrou sur la ligne du compte : une fiche ouverte avant le départ ne peut plus le défaire, et deux départs ne se croisent pas. Un compte désactivé dans l'administration mais encore logé reste dans la liste et peut recevoir son départ. Un compte d'administration (is_staff, super-utilisateur) n'est jamais traité comme résident. Les éducateurs ne voient que les résidents actuels (minimisation des données). Les sessions sont lues avant la transaction, puis supprimées avec le moteur de sessions configuré. 18 tests.

### E2 Connexion

#### T10 Couche fournisseur SMS (fait le 5 nov. 2026)
- **Docs** : [SMSGate](https://docs.sms-gate.app), [API SMS OVHcloud](https://docs.ovhcloud.com/fr/guides/web-cloud/messaging/sms/sending-via-api-c.md), [python-ovh](https://github.com/ovh/python-ovh), [contrôles Django](https://docs.djangoproject.com/en/6.1/topics/checks/), [lanceur de tests](https://docs.djangoproject.com/en/6.1/topics/testing/advanced/#defining-a-test-runner).
- [x] Interface `FournisseurSms.envoyer(numero, texte)` et point d'entrée unique `envoyer_sms()` ; fournisseur actif choisi par `DJANGO_SMS_FOURNISSEUR` (application `sms`)
- [x] Fournisseur « console » pour le développement, et « mémoire » pour les tests : le lanceur de tests l'impose, aucun test ne peut envoyer un vrai SMS
- [x] Fournisseur SMSGate (téléphone Android) : mode local (identifiant et mot de passe) ou nuage (jeton)
- [x] Fournisseur OVHcloud pour la production, avec la bibliothèque officielle python-ovh (signature des requêtes)
- [x] Compteur de caractères et de segments (GSM-7 : 160 ou 153, UCS-2 : 70 ou 67), avec la table d'extension GSM, les emoji et la liste des caractères qui imposent l'UCS-2
- [x] Erreurs classées « temporaire » ou non, pour les relances de T21 ; contrôle `manage.py check` des options manquantes ; commande `envoyer_sms_essai`
- **Notes** : les journaux ne contiennent jamais le numéro complet ni le texte (un code de connexion y passerait). Un message est limité à 6 SMS. OVHcloud : `noStopClause` est activé, car nos messages sont des informations de service ; sans lui, OVHcloud bloque l'envoi entre 20 h et 8 h. Expéditeur : le numéro court d'OVHcloud par défaut (il permet de répondre), ou un nom déclaré. En français, « ê â î ô û ç » et l'apostrophe typographique font passer le message en UCS-2 (70 caractères) : T20 l'affichera à la rédaction. Aucun identifiant dans le dépôt : tout vient de l'environnement.
- **Revue indépendante (5 nov.)** : corrigé après relecture. Avec `--parallel` en mode « spawn » (macOS, Windows, Python 3.14), les processus de test relisaient le fournisseur réel : le lanceur l'impose maintenant dans chaque processus (vérifié avec `DJANGO_SMS_FOURNISSEUR=ovh`). Un délai de réponse dépassé ou une acceptation sans identifiant sont « incertains » : le SMS est peut-être parti, donc pas de relance automatique (risque de doublon). OVHcloud 429 est temporaire. Un numéro de forme correcte mais inexistant ou fixe est refusé avant l'envoi. En production, sans `DJANGO_SMS_FOURNISSEUR`, aucun SMS ne part et rien n'est écrit dans les journaux (fournisseur « aucun »). 39 tests, sans aucun appel réseau.

#### T11 Code d'activation (fait le 5 nov. 2026)
- **Maquettes** : P5 (bouton), R0.
- **Docs** : [module secrets](https://docs.python.org/3/library/secrets.html), [module hmac](https://docs.python.org/3/library/hmac.html), [segno](https://pypi.org/project/segno/), [never_cache](https://docs.djangoproject.com/en/6.1/topics/http/decorators/#caching), [cycle_key](https://docs.djangoproject.com/en/6.1/topics/http/sessions/#django.contrib.sessions.backends.base.SessionBase.cycle_key).
- [x] Généré depuis la fiche du résident (permission `generer_code_activation` : Accueil, Administration), quand la personne se présente ; noté dans le journal d'audit
- [x] Code de 10 caractères sans lettres ambiguës (« ABCDE-FGHJK »), empreinte HMAC en base, usage unique, valable 72 h ; un nouveau code annule l'ancien ; le départ annule le code en cours
- [x] Page imprimable, montrée une seule fois (jamais en cache), avec un code QR qui ouvre /activer/ et remplit le code
- [x] Limite de tentatives : 10 codes faux par adresse IP et par heure, puis blocage
- [x] Page résident /activer/ (étape 1 sur 3) ; le parcours dure une heure au plus, avec une nouvelle clé de session
- [x] Import (T08) : option « envoyer par SMS un code aux nouveaux », décochée par défaut
- [x] Retour d'un ancien résident (T09) : choix de la chambre, compte réactivé, puis nouveau code
- **Notes** : le code QR contient l'adresse avec le code après « # » : le navigateur ne l'envoie jamais au serveur, et la page l'efface de l'adresse. L'option SMS de l'import est moins sûre qu'une remise en main propre (pas de contrôle d'identité) : l'écran le dit. Le code est marqué utilisé dès la saisie ; si la personne s'arrête en route, l'accueil lui en donne un autre. Correctif général : la bordure rouge des champs en erreur ne s'affichait pas (spécificité CSS), c'est réparé.
- **Revue indépendante (5 nov.)** : corrigé après relecture. Un code remplacé ou annulé pendant la saisie passait encore (la mise à jour « usage unique » revérifie maintenant tout). La limite par adresse IP aurait permis à une personne de bloquer tout le wifi de la résidence : 10 échecs par navigateur et 50 par adresse. Recharger la page du code en générait un nouveau et annulait celui déjà remis : la page passe par une redirection et ne s'affiche qu'une fois. Au retour d'un ancien résident, son ancienne connexion ne le fait plus passer pour « activé ». L'envoi des codes par SMS à l'import est limité à 20 et ne peut plus casser l'import. Le lien « Enregistrer un retour » est visible avec le seul droit de gérer les résidents.

#### T12 Vérification du téléphone par code SMS (fait le 5 nov. 2026)
- **Maquette** : R0.
- **Docs** : [module secrets](https://docs.python.org/3/library/secrets.html), [hmac.compare_digest](https://docs.python.org/3/library/hmac.html#hmac.compare_digest), [chargement des modèles (from_db)](https://docs.djangoproject.com/en/6.1/ref/models/instances/#customizing-model-loading), [expressions F](https://docs.djangoproject.com/en/6.1/ref/models/expressions/#f-expressions).
- [x] Étape 2 de /activer/ : le code part seulement quand la personne le demande (rien n'est envoyé sur un simple affichage)
- [x] Code à 6 chiffres (module `secrets`), empreinte HMAC, valable 10 minutes, 5 essais au plus, comptés en base même avec des envois simultanés
- [x] Délai de 60 secondes avant renvoi, 3 envois par heure au plus ; un nouveau code remplace l'ancien
- [x] Message clair si le numéro n'est pas le bon (« Ce n'est pas mon numéro » : passer à l'accueil) ou s'il n'y a pas de numéro
- [x] Le compte garde le numéro vérifié et la date (`telephone_verifie`, `telephone_verifie_le`) ; un autre numéro n'est jamais considéré comme vérifié, quelle que soit la façon dont il a changé
- [x] Étape 3 : en attendant T13, page « Téléphone vérifié, la clé d'accès arrive bientôt »
- **Notes** : un SMS qui n'a pas pu partir rend son code inutilisable, mais compte dans la limite horaire (pour ne pas épuiser le crédit SMS). Le code n'est jamais dans les journaux (voir T10). Le champ utilise `autocomplete="one-time-code"` : iOS et Android proposent le code reçu.
- **Revue indépendante (5 nov.)** : corrigé après relecture. Des clics en rafale passaient les limites d'envoi : la ligne du compte est verrouillée avant les vérifications. Le suivi des changements de numéro avait des trous (chargement partiel, `update()`, instance périmée) : on compare désormais au numéro vérifié. L'étape 3 revérifie le numéro. Un nouveau code d'activation ferme la session ouverte avec l'ancien (un code volé ne garde pas la main). La page du code ne garde plus le code en clair dans la session : un jeton à usage unique évite qu'un rechargement remplace le code remis. Afficher « Ce n'est pas mon numéro » ne change plus rien (GET). L'heure de renvoi est affichée au lieu d'un compte à rebours figé. Au plus 15 essais par heure et par personne (3 codes de 5 essais). 27 tests.

#### T13 Connexion par clé d'accès (passkey) (fait le 5 nov. 2026)
- **Docs** : [django-otp-webauthn](https://django-otp-webauthn.readthedocs.io/en/stable/) (démarrage, vues, classe « helper », FAQ, journal des versions, code source), [MDN : Web Authentication API](https://developer.mozilla.org/fr/docs/Web/API/Web_Authentication_API), [MDN : parseCreationOptionsFromJSON](https://developer.mozilla.org/en-US/docs/Web/API/PublicKeyCredential/parseCreationOptionsFromJSON_static), [sessions Django (set_expiry)](https://docs.djangoproject.com/en/6.1/topics/http/sessions/), [authentification Django (login, backends)](https://docs.djangoproject.com/en/6.1/topics/auth/default/).
- [x] Création de la clé après la vérification du téléphone : étape 3 de /activer/, puis connexion directe. Clé « découvrable » obligatoire (connexion sans identifiant)
- [x] Connexion sans mot de passe sur /connexion/ : Face ID, empreinte ou code du téléphone, toujours exigés
- [x] Récupération : nouveau code d'activation par l'accueil. La nouvelle clé remplace les anciennes et ferme les autres sessions. La fiche du résident montre la date de la clé
- [x] Sessions longues pour les résidents (90 jours sans activité), 12 heures pour le personnel. Page /connexion/confirmer/ et décorateur `confirmation_recente` : clé utilisée il y a moins de 10 minutes, pour les actions sensibles (wifi en T16)
- [x] Au départ (T09) : clés supprimées via le signal `depart_enregistre`, nombre noté au journal
- [x] Déconnexion (POST), accueil provisoire du résident (en attendant T34), clés visibles et supprimables dans l'administration
- [x] Téléphone perdu ou volé : bouton « Couper l'accès » sur la fiche (Accueil, Administration). Clés supprimées, code en attente annulé, sessions fermées, entrée au journal
- **Notes** : version 0.10.3 de la bibliothèque, qui corrige une faille d'ajout de clé (GHSA-8r76-c459-ww98). Elle n'a pas de traduction française et son script affiche des fenêtres `alert()` : la doc dit de faire son propre script dans ce cas. `cle-acces.js` appelle les mêmes adresses avec le même JSON, sans dépendance. Les tests utilisent un authentificateur logiciel (vraie clé ES256) : le serveur vérifie tout, sans simulacre. Essai de bout en bout dans Chromium avec un authentificateur virtuel : activation, connexion, confirmation, annulation. En développement, ouvrir http://localhost:8000 (pas 127.0.0.1). Le personnel garde la connexion par mot de passe de l'administration jusqu'à T14.
- **Revue indépendante (5 nov.)** : corrigé après relecture. Un téléphone perdu restait connecté : supprimer une clé (administration, « Couper l'accès ») ferme maintenant les sessions du compte. La création de clé revérifie tout une fois la ligne du compte verrouillée, et la génération d'un code prend le même verrou (un départ simultané ne laisse plus de clé). Face ID, empreinte ou code exigés dès la création, sinon une clé inutilisable aurait remplacé les autres. Un compte devenu membre du personnel ne s'active plus par ce chemin. Changer les rôles ferme les sessions de la personne et annule son code. La durée de session repart à chaque requête (`SESSION_SAVE_EVERY_REQUEST`). Un identifiant de clé déjà connu renvoie une erreur claire au lieu d'une erreur 500. Messages du script plus justes (réseau coupé, page expirée). 340 tests.

#### T14 Sécurité de l'espace équipe (fait le 5 nov. 2026)
- **Docs** : [django-otp (OTPMiddleware, is_verified, OTPAdminSite)](https://django-otp-official.readthedocs.io/en/stable/), [remplacer le site d'administration](https://docs.djangoproject.com/en/6.1/ref/contrib/admin/#overriding-the-default-admin-site), [permissions dans un backend](https://docs.djangoproject.com/en/6.1/topics/auth/customizing/#handling-authorization-in-custom-backends), [middleware](https://docs.djangoproject.com/en/6.1/topics/http/middleware/), [API bas niveau du cache](https://docs.djangoproject.com/en/6.1/topics/cache/#the-low-level-cache-api), [commandes d'administration](https://docs.djangoproject.com/en/6.1/howto/custom-management-commands/), [contrôles système](https://docs.djangoproject.com/en/6.1/topics/checks/).
- [x] Espace équipe réservé au personnel : un middleware protège /equipe/, /guide/ et l'administration (anonyme : connexion ; résident : refus ; personnel sans clé vérifiée : confirmation). Les vues gardent leurs permissions
- [x] Clé d'accès obligatoire pour le personnel, et plus aucun mot de passe : la connexion par mot de passe est coupée (les permissions des rôles restent), l'administration exige une session vérifiée par clé et renvoie vers /connexion/
- [x] Premier accès du personnel : code d'activation généré par un administrateur (action « Générer un code d'activation (personnel) »), puis SMS et clé, comme les résidents. Un code du personnel ne sert pas à un résident, et inversement. Premier administrateur : `python manage.py code_activation <identifiant> --telephone "06 …"`
- [x] Adresse de l'administration réglable (`DJANGO_ADMIN_URL`) ; `check --deploy` signale « admin/ » (connexion.W001)
- [x] Limite de tentatives de connexion par adresse IP : 300 débuts de connexion en 10 minutes (réponse 429). Une adresse IPv6 compte pour son réseau /64
- [x] `check` refuse une adresse d'administration déjà prise (/connexion/, /equipe/…) (connexion.E001)
- **Notes** : retirer ModelBackend coupait aussi les permissions (c'est lui qui les lit) : un backend `PermissionsSansMotDePasse` garde les permissions et refuse tout mot de passe. Les comptes se créent sans mot de passe dans l'administration. Les compteurs des limites sont dans le cache de Django, en mémoire par processus tant qu'aucun cache partagé n'est choisi (T38). Essai de bout en bout dans Chromium : activation d'un administrateur, puis espace équipe et administration.
- **Revue indépendante (5 nov.)** : corrigé après relecture. Le blocage après 30 échecs permettait à n'importe qui de bloquer tout le wifi de la résidence avec des requêtes vides : il est retiré, car une clé d'accès ne se devine pas ; seule la limite des débuts reste, plus large. Une personne qui pouvait seulement modifier des comptes pouvait se donner le rôle Administration et le statut de super-utilisateur : les rôles et l'accès technique demandent maintenant le rôle Administration, et le statut de super-utilisateur demande d'en être un. Le code d'un super-utilisateur ne peut venir que d'un super-utilisateur. Ajouter un rôle ne supprime plus le code du personnel déjà remis. Une adresse d'administration déjà prise est refusée. Un test prouvait moins qu'il ne disait. 367 tests.

### Qualité

#### T14b Code en anglais (fait le 5 nov. 2026)
- Décidé le 5 nov. 2026, fait juste après T14.
- [x] Noms en anglais : applications (`accounts`, `access`, `activation`, `audit`, `housing`, `residents`, `sms`, `ui`, `tools`), modèles, champs, fonctions, variables, noms d'URL, gabarits, classes et variables CSS, JavaScript, tests et fichiers de test
- [x] Commentaires et docstrings en anglais
- [x] Les textes affichés restent en français ; les adresses visibles (/activer/, /connexion/, /equipe/…) aussi
- [x] Migrations recréées depuis zéro (aucune donnée réelle), base de développement recréée
- [x] Mêmes tests (367), W3C, contrôle avant déploiement et essais de bout en bout (résident et administrateur) qu'avant ; documentation mise à jour
- **Notes** : le [glossaire](docs/glossaire.md) relie chaque ancien nom au nouveau. Traduction faite en parallèle, application par application, avec ce glossaire comme référence unique. Contrôles en plus : la feuille de style a gardé exactement la même structure (chaque ancienne classe correspond à une seule nouvelle), chaque classe utilisée dans un gabarit existe, et les captures d'écran des pages des résidents sont identiques au pixel près. Changements pour l'installation : variables d'environnement renommées (`DJANGO_SMS_PROVIDER`, `DJANGO_WEBAUTHN_ORIGINS`, `SMSGATE_TOKEN`, `SMSGATE_USERNAME`, `SMSGATE_PASSWORD`, `OVH_SMS_SENDER`), commande `activation_code --phone`. Les paramètres de filtre de la liste des résidents sont en anglais (`?floor=`, `?account=`).
- **Revue indépendante (5 nov.)** : aucun changement de comportement trouvé (code comparé module par module, variables des gabarits suivies pendant les tests). Corrigé : des champs sans libellé s'affichaient en anglais dans l'administration (« User » au lieu de « utilisateur ») ; les erreurs d'envoi de SMS lues par l'exploitant sont revenues en français, comme les contrôles et les commandes ; trois noms harmonisés. La règle de langue est écrite dans le glossaire.

### E3 Wifi

#### T15 Accès wifi chiffré (équipe) (fait le 5 nov. 2026)
- **Maquette** : S-Residents (colonne « Wifi valable jusqu'au »).
- **Docs** : [cryptography : Fernet et MultiFernet](https://cryptography.io/en/latest/fernet/), [module secrets](https://docs.python.org/3/library/secrets.html), [Prefetch](https://docs.djangoproject.com/en/6.1/ref/models/querysets/#prefetch-objects), [contraintes](https://docs.djangoproject.com/en/6.1/ref/models/constraints/), [contrôles système](https://docs.djangoproject.com/en/6.1/topics/checks/).
- [x] Modèle `WifiAccess` (application `housing`) : mot de passe chiffré avec Fernet, clés dans `DJANGO_WIFI_KEYS`, jamais dans le dépôt. Un seul accès actif par chambre ; le renouvellement garde l'historique. `check` signale une clé absente ou invalide (housing.E001). Commande `rotate_wifi_keys` pour changer de clé
- [x] Saisie ou génération par l'accueil et l'administration, depuis la fiche du résident : mot de passe donné par le réseau, ou généré (12 caractères, sans I, l, O, 0 ni 1) et affiché une seule fois. Date d'expiration à un an, modifiable. Confirmation par clé d'accès de moins de 10 minutes, jeton à usage unique (un rechargement ne génère pas deux fois)
- [x] Affichage réservé aux administrateurs (`view_wifi_password`), après confirmation par clé d'accès, page jamais mise en cache, chaque affichage dans le journal à leur nom. Les listes ne montrent jamais de mot de passe
- [x] Au départ (T09) : accès wifi de la chambre coupé, via le signal `departure_recorded`, noté dans le journal ; le message du départ rappelle de changer l'accès sur le réseau. Un changement de chambre coupe aussi l'accès de l'ancienne
- [x] Liste des résidents : colonne « Wifi valable jusqu'au », avec « dans N j » à 30 jours de l'expiration et « Expiré » ensuite (une seule requête de plus, quel que soit le nombre de résidents)
- **Notes** : la table des consultations prévue (`WIFI_VIEW`) n'est pas créée : chaque affichage est une entrée du journal d'audit, qui garde déjà qui, quand et depuis quelle adresse. L'application ne change pas le mot de passe sur le réseau lui-même : elle note l'accès, et la coupure rappelle de le changer. En développement, la clé est dérivée de la clé secrète de développement. Captures vérifiées (mobile et ordinateur, clair et sombre).
- **Revue indépendante (5 nov.)** : aucun moyen d'afficher un mot de passe sans droit, sans confirmation ou sans trace. Corrigé : un enregistrement au moment d'un départ pouvait laisser un accès actif sur une chambre vide (l'enregistrement revérifie le séjour sous le verrou de la chambre, et la coupure prend le même verrou) ; la correction de chambre le jour de l'arrivée ne coupait pas la première ; un double clic pouvait afficher un mot de passe déjà remplacé (le formulaire indique l'accès qu'il a vu, et rien n'est enregistré si un autre est arrivé entre-temps) ; un mot de passe saisi revenait dans la page en cas d'erreur ; sans clé, erreur 500 (la production refuse maintenant de démarrer sans `DJANGO_WIFI_KEYS`, et les pages affichent un message) ; le jeton du formulaire est lié à la chambre ; le message du départ ne parle du wifi que s'il y en avait un. Mots de passe masqués dans les rapports d'erreur de Django. 405 tests.

#### T15b Format du portail wifi et import de la liste (fait le 5 nov. 2026)
- **Pourquoi** : le portail captif de la résidence utilise 6 caractères pour l'identifiant et 6 pour le mot de passe (par exemple `vre8th` / `72ptmk`). L'équipe tient déjà une liste identifiant, chambre, personne. Le format peut changer un jour (7, 8 ou 12 caractères).
- **Docs** : [ModelAdmin](https://docs.djangoproject.com/en/6.1/ref/contrib/admin/), [validateurs](https://docs.djangoproject.com/en/6.1/ref/validators/), [module secrets](https://docs.python.org/3/library/secrets.html), [openpyxl en lecture seule](https://openpyxl.readthedocs.io/en/3.1/optimized.html).
- [x] Page « Réglages wifi » dans l'administration (permission `manage_wifi_settings`, rôle Administration) : longueur de l'identifiant, longueur du mot de passe, caractères permis, nom du réseau. Par défaut 6 et 6, minuscules et chiffres sans l, o, 0 ni 1. Changer le format ne demande aucune modification du code
- [x] Saisie libre : de 4 à 64 caractères sans espace, pour ne jamais bloquer l'équipe si le portail change. L'ancienne limite de 8 à 63 caractères aurait refusé les vrais mots de passe
- [x] Génération au format réglé : identifiant, mot de passe, ou les deux, laissés vides dans le formulaire. Les valeurs générées s'affichent une seule fois. Un identifiant ne peut servir qu'à une chambre à la fois (contrainte)
- [x] Import de la liste existante (CSV ou Excel), réservé aux administrateurs après confirmation par clé d'accès : aperçu ligne par ligne, puis enregistrement des lignes prêtes, tout ou rien. Colonnes : Identifiant, Mot de passe, Chambre (obligatoires), Résident (sert à vérifier), Valable jusqu'au (vide : un an). Modèle .csv à télécharger
- **Notes** : les mots de passe du fichier sont chiffrés dès la lecture ; ils n'apparaissent ni dans l'aperçu ni en clair dans la session, et l'aperçu expire après 30 minutes. Chaque accès importé va au journal d'audit, au nom de la personne qui importe. Une chambre sans résident est refusée : il faut d'abord importer ou créer sa fiche. Un nombre lu par Excel (par exemple `012345` devenu `12345`) donne un avertissement. Au renouvellement, le formulaire reprend l'identifiant actuel ; on le vide pour en générer un autre. Le nom du réseau servira à l'écran « Mon wifi » (T16). Captures vérifiées (mobile et ordinateur, clair et sombre).
- **Revue indépendante (5 nov.)** : corrigé : un mot de passe lu comme un nombre par Excel apparaissait en clair dans un avertissement (aucun message ne cite plus un mot de passe) ; des colonnes « Code » ou « Utilisateur » étaient prises sans rien dire pour le mot de passe ou l'identifiant (titres retirés, deux colonnes pour un même champ refusent le fichier) ; une valeur abîmée par Excel (`2,34E+58`) passait (refusée maintenant, et un format différent de celui du portail donne un avertissement) ; le même identifiant enregistré au même moment pour deux chambres donnait une erreur 500 (message clair) ; renvoyer la même liste remplaçait tous les accès et repoussait leur date de fin (les lignes identiques sont « Déjà à jour » et ne changent rien) ; un second clic disait à tort que rien n'avait été enregistré ; la migration s'arrête avec un message clair si deux accès actifs ont déjà le même identifiant ; les caractères permis sont limités aux lettres sans accent, chiffres et signes. Les pages d'import demandent aussi `manage_residents`. 437 tests.

#### T16 Écran « Mon wifi » du résident (fait le 5 nov. 2026)
- **Maquette** : R6.
- **Docs** : [Clipboard.writeText (MDN)](https://developer.mozilla.org/en-US/docs/Web/API/Clipboard/writeText), [NetworkInformation (MDN)](https://developer.mozilla.org/en-US/docs/Web/API/NetworkInformation/type), [cache des réponses](https://docs.djangoproject.com/en/6.1/topics/cache/#controlling-cache-using-other-headers).
- [x] Page `/wifi/`, raccourci « Mon wifi » sur l'accueil du résident : nom du réseau, identifiant, date de fin et barre de validité (« encore 10 mois », « encore 12 jours »). Rappel si l'accès se termine dans 30 jours ou a expiré
- [x] Mot de passe masqué, affiché par le bouton « Afficher » après confirmation par la clé d'accès de moins de 10 minutes. Chaque affichage va au journal d'audit, au nom du résident. Page jamais mise en cache
- [x] Boutons « copier » pour l'identifiant et le mot de passe (Clipboard API), avec un message « copié ». Sans JavaScript ou sans presse-papiers, les boutons restent cachés et le texte se sélectionne d'un appui
- [x] Nom du réseau (SSID) : saisi par un administrateur dans « Réglages wifi ». Sans nom, la page dit de le demander à l'accueil
- **Notes** : une page web ne peut pas lire le nom du réseau du téléphone : l'API NetworkInformation ne donne que le type de connexion et la vitesse, et seulement dans Chrome. Le serveur ne le voit pas non plus. Il pourrait venir du portail captif lui-même, si son logiciel a une API : à voir avec la marque du portail. « Me prévenir avant l'expiration » arrive avec T17, et « prévenir l'accueil » avec les signalements (T30). Copie vérifiée dans Chromium. Captures vérifiées (mobile et ordinateur, clair et sombre).
- **Revue indépendante (5 nov.)** : aucun moyen de voir l'accès d'une autre chambre (changement de chambre, départ, compte du personnel sans chambre : testés). Corrigé : le mot de passe s'affichait sur une simple visite de l'adresse, donc aussi au retour arrière, au rechargement ou au préchargement du navigateur, avec une entrée de journal à chaque fois (il s'affiche maintenant seulement par le bouton « Afficher ») ; le message « copié » pouvait rester muet pour un lecteur d'écran ; la barre de validité utilisait un style en ligne, qu'une future politique de sécurité du contenu (T37) bloquerait (dessin SVG) ; textes précisés (« A expiré le », bouton « Afficher le mot de passe » pour les lecteurs d'écran, message en cas de mot de passe illisible). 453 tests.

#### T17 Rappels d'expiration du wifi (fait le 5 nov. 2026)
- **Maquette** : R6 (« Me prévenir avant l'expiration »), S-Residents.
- [x] Notification au résident 15 jours avant la fin de l'accès de sa chambre, par la commande quotidienne `send_wifi_reminders` (à planifier sur le serveur, voir le README). Un seul rappel par accès ; si aucun appareil n'a été atteint, nouvel essai les jours suivants, jusqu'à la fin. Un accès renouvelé repart avec un nouveau rappel
- [x] Le résident peut désactiver le rappel sur sa page wifi. Sans appareil abonné, la page l'invite à activer les notifications
- [x] Page « Accès wifi à renouveler » pour l'équipe (`/equipe/residents/wifi/renouvellements/`) : accès qui se terminent dans les 30 jours ou déjà terminés, du plus urgent au moins urgent, avec l'état du rappel et le lien « Renouveler ». Lien avec le nombre en haut de la liste des résidents
- **Notes** : la liste ne montre ni l'identifiant ni le mot de passe. La colonne « Rappel au résident » dit si le rappel est prévu, envoyé, désactivé, ou impossible faute d'appareil (dans ce cas, prévenir le résident en personne). Le rappel passe seulement par les notifications (pas de SMS, pour ne pas en payer un par résident chaque année).
- **Revue indépendante (5 nov.)** : corrigé : la ligne cron du README aurait tourné avec les réglages de développement et une mauvaise clé VAPID (ligne complète avec les réglages de production, le fichier d'environnement, `flock` et une heure en journée) ; deux exécutions en même temps pouvaient envoyer deux fois, et un accès renouvelé pendant l'exécution recevait quand même un rappel (le rappel est réservé avant l'envoi, puis libéré s'il n'a pas pu partir) ; une erreur pour un résident n'arrête plus les autres ; un appui après une session expirée affichait une erreur 405 ; date du message écrite comme sur les pages (« le 2 janvier »). 521 tests.

### E4 Messages

#### T18 Application installable (PWA) (fait le 5 nov. 2026)
- **Docs** : [rendre une PWA installable (MDN)](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Guides/Making_PWAs_installable), [manifeste (MDN)](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Manifest), [service workers (MDN)](https://developer.mozilla.org/en-US/docs/Web/API/Service_Worker_API/Using_Service_Workers), [Web Push sur iOS (WebKit)](https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/), [Pillow ImageDraw](https://pillow.readthedocs.io/en/stable/reference/ImageDraw.html).
- [x] Manifeste `/manifest.webmanifest` (nom, icônes 192 et 512 dont une « maskable », `display: standalone`), lié depuis chaque page. Icônes tirées du logo par `tools/make_icons.py` : `favicon.ico`, icône SVG, icône pour l'écran d'accueil de l'iPhone. `/favicon.ico` renvoie vers le fichier
- [x] Service worker `/sw.js`, servi à la racine pour couvrir tout le site. Les pages viennent toujours du réseau : aucune page avec des données personnelles n'entre dans le cache. Sans réseau, la page « Pas de connexion » s'affiche. Le cache ne garde que des fichiers publics (page hors ligne, feuille de style, polices, logo) et change de nom quand l'un d'eux change
- [x] Page `/installer/` : étapes pour iPhone (Safari, Partager, « Sur l'écran d'accueil ») et Android (Chrome, « Installer l'application »), et bouton « Installer » quand le navigateur le propose. Raccourci « Installer l'application » sur l'accueil du résident, caché quand l'application est déjà ouverte depuis son icône
- **Notes** : vérifié dans Chromium : aucune erreur d'installation, cache limité aux fichiers publics, page hors ligne avec sa mise en forme, la page wifi jamais en cache. Sur iPhone, l'installation ne se fait que par le menu Partager (pas de bouton possible). Pillow ne sert qu'à dessiner les icônes, en développement.
- **Revue indépendante (5 nov.)** : aucun problème de données personnelles. Corrigé : la vérification de mise à jour du service worker renouvelait la session, si bien qu'un téléphone perdu qui reçoit des notifications (T19) serait resté connecté indéfiniment (les fichiers publics de l'application n'utilisent plus la session) ; les étapes pour iPhone suivent iOS 26 (« ⋯ » puis « Partager ») et rappellent de se reconnecter une fois dans l'application ; « Réessayer » recharge la page demandée ; la suggestion d'installation de Chrome n'est plus bloquée sur les autres pages ; requêtes HEAD acceptées, redirection temporaire pour `/favicon.ico`. 465 tests.

#### T19 Notifications Web Push (fait le 5 nov. 2026)
- **Docs** : [Push API (MDN)](https://developer.mozilla.org/en-US/docs/Web/API/Push_API), [PushManager.subscribe (MDN)](https://developer.mozilla.org/en-US/docs/Web/API/PushManager/subscribe), [pywebpush](https://github.com/web-push-libs/pywebpush) 2.5.0, [Web Push sur iOS (WebKit)](https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/).
- [x] Clé VAPID dans `DJANGO_VAPID_PRIVATE_KEY` (obligatoire en production, créée par `python manage.py vapid_key`), contact dans `DJANGO_VAPID_CONTACT`. En développement, clé dérivée de la clé secrète. Contrôles `push.E001` et `push.E002`
- [x] Modèle `PushSubscription` (application `push`) : un appareil par navigateur, au plus 10 par personne. L'adresse du service d'envoi n'apparaît jamais dans une page, l'administration ou les journaux. Seuls les services connus (Google, Mozilla, Apple, Microsoft) sont acceptés, pour que le serveur n'envoie jamais de requête ailleurs
- [x] Page « Notifications » (`/notifications/`) pour les résidents et l'équipe : l'autorisation est demandée seulement après un appui sur « Activer les notifications ». Sur iPhone hors application installée, la page renvoie vers « Installer l'application ». Liste des appareils, arrêt d'un appareil, notification d'essai (une par minute)
- [x] Le service worker affiche le message et ouvre sa page au toucher, seulement une page du site
- [x] Nettoyage : appareil supprimé quand le service d'envoi répond 404 ou 410, après 5 échecs d'affilée, à la déconnexion (l'appareil de cette session), quand une clé d'accès est supprimée (téléphone perdu, départ, nouvelle activation). Commande `prune_push_subscriptions` pour les comptes désactivés
- **Notes** : sur un téléphone partagé, l'appareil reste à la personne qui a appuyé sur « Activer » : une autre personne qui se connecte ne reçoit rien tant qu'elle n'a pas activé elle-même. L'envoi part pendant la requête, appareil par appareil (10 secondes au plus chacun) : les envois en nombre passeront par une tâche de fond avec T21. Vérifié dans Chromium : affichage d'un message par le service worker (titre, texte, icône, page à ouvrir). L'abonnement réel ne peut pas être essayé ici (les services d'envoi ne sont pas joignables depuis l'environnement de travail) : à essayer sur un téléphone.
- **Revue indépendante (5 nov.)** : corrigé : une adresse truquée (`https://pirate.example\\.fcm.googleapis.com/`) passait le contrôle des services connus, et l'envoi suivait les redirections (adresse vérifiée par un motif strict, redirections refusées) ; un appareil aux clés invalides arrêtait l'envoi à tous les autres (clés vérifiées à l'abonnement, toute erreur d'un appareil reste limitée à lui) ; sur un téléphone partagé, la personne précédente continuait de recevoir ses notifications après la fin de sa session (l'appareil est retiré dès qu'une autre personne s'y connecte) ; la déconnexion pouvait oublier l'appareil (le serveur demande maintenant à chaque nouvelle session) ; après un changement de clé VAPID, l'activation échouait toujours (l'ancien abonnement est retiré d'abord) ; une panne passagère d'un service d'envoi (429, 5xx, délai dépassé) ne compte plus comme un échec ; un appareil repris par une autre personne prend une nouvelle date ; clé de développement toujours valide. Note : la limite d'une notification d'essai par minute vaut par processus tant qu'aucun cache partagé n'est configuré (T38). 500 tests.

#### T20 Modèles de message et composeur (fait le 5 nov. 2026)
- **Maquette** : P2.
- **Docs** : [ModelForm et cases à cocher multiples](https://docs.djangoproject.com/en/6.1/topics/forms/modelforms/), [formaction (MDN)](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/button#formaction), norme GSM 03.38 (déjà dans `sms/segments.py`).
- [x] Types : visite de logement, maintenance, annonce ou événement, vote ou avis, message libre
- [x] Modèles modifiables par l'équipe (`/equipe/messages/modeles/`), six modèles de départ. Champs `{prénom}`, `{chambre}`, `{date}`, `{début}`, `{fin}` : un champ inconnu est refusé, et le composeur prévient s'il manque une date ou une heure
- [x] Ciblage par étage, « tout le monde », chambre ou personne ajoutée, et personne retirée. Décompte « notification (gratuit) / SMS / sans moyen de contact », liste des destinataires avec leur canal
- [x] Version SMS : les caractères français hors de l'alphabet SMS (ê, ç, œ, ’, « ») sont remplacés, ce qui garde 160 caractères par SMS. Alerte quand un caractère (un emoji par exemple) fait encore passer en UCS-2, avec le coût par personne. Longueur du SMS le plus long, et coût total
- [x] « M'envoyer un test » : notification sur ses appareils, et SMS sur son téléphone si coché (un essai par minute)
- **Notes** : le composeur enregistre des brouillons ; l'envoi aux résidents, maintenant ou programmé, arrive avec T21. Aperçus calculés pour le premier destinataire.
- **Revue indépendante (5 nov.)** : rien ne fuit vers les résidents. Corrigé : « Remettre » ne ramenait pas une personne ajoutée par son nom ; quand le formulaire avait une erreur, le bouton pressé ne faisait rien sans le dire (résumé des erreurs en haut) ; « n° », les traits d'union du téléphone et les ligatures restaient hors de l'alphabet SMS, et un caractère pouvait changer de sens ; une personne ajoutée devenue membre de l'équipe restait destinataire ; Entrée dans un champ lançait « Ajouter » ; un brouillon perdait son lien avec le modèle ; les champs du titre n'étaient ni vérifiés ni remplis ; l'aperçu SMS montre maintenant le plus long ; accords (« recevra », « Voir le destinataire ») ; suppression confirmée ; pas d'essai tant qu'une date ou une heure manque ; nombre de requêtes constant quel que soit le nombre de personnes ajoutées. 547 tests.

#### T21 Envoi programmé et relances (fait le 5 nov. 2026)
- **Docs** : [framework de tâches de Django](https://docs.djangoproject.com/en/6.1/topics/tasks/), [django-tasks-db](https://github.com/RealOrangeOne/django-tasks-db) 0.13.0 (code lu : file d'attente en base, *worker* `db_worker`, verrou exclusif sur SQLite, pas de nouvel essai automatique), réglages SQLite `transaction_mode` et `init_command` de Django.
- [x] Backend de production : **django-tasks-db**. La file d'attente vit dans la base existante (SQLite convient), sans Redis ni autre service, et son *worker* tourne comme un service. En développement et dans les tests : `ImmediateBackend`
- [x] Commande `run_scheduled`, chaque minute : lance les messages et relances arrivés à l'heure, reprend les envois interrompus ou en attente d'un nouvel essai, enregistre les départs prévus. Une tâche n'est remise dans la file que si la précédente date de plus de 10 minutes : rien ne s'empile quand le *worker* est arrêté. Un message en retard de plus de 12 heures, ou une relance de 8 h encore pas partie à midi, ne part plus et c'est noté dans le journal
- [x] Notification d'abord. SMS seulement pour une personne sans aucun appareil. Une notification qui ne passe pas (service d'envoi en panne) est réessayée trois fois, jamais remplacée par un SMS payant
- [x] Sans doublon : un `Delivery` par personne et par sorte (message, relance), contrainte unique, et chaque envoi est « réservé » avant de partir. Un envoi coupé en plein milieu n'est jamais renvoyé : il passe en échec « état inconnu ». Un SMS en échec passager est réessayé, un SMS « incertain » jamais
- [x] Relance le jour J à 8 h de ceux qui n'ont pas répondu (`AttendanceReply`, les boutons pour répondre arrivent avec T22), par leur canal du jour. Elle peut être annulée tant qu'elle n'est pas partie
- [x] Écrans : section « 4. Quand ? » du composeur, page de confirmation (destinataires, coût, problèmes qui bloquent l'envoi), page de suivi (bilan, état de chaque envoi, annulation ou retour au brouillon d'un envoi programmé), liste « À venir », « Brouillons », « Envoyés »
- [x] Départ prévu (T09) : une date future dans le formulaire de départ le prévoit. Il est enregistré automatiquement ce jour-là à midi, garde sa date après un changement de chambre, et peut être déplacé ou annulé. Journal : « Départ prévu », « Départ prévu annulé »
- **Notes** : tant que les résidents ne peuvent pas répondre (T22), la relance va à tous ceux qui ont reçu le message ; la page de confirmation donne son coût en SMS. La chambre reste occupée jusqu'à midi le jour du départ prévu. L'exploitation (service du *worker*, lignes cron, nettoyage des tâches) est décrite dans le README.
- **Revue indépendante (5 nov.)** : corrigé : une notification en échec passager devenait un SMS payant, parfois en double (nouvel essai de la notification) ; un message pouvait passer « Envoyé » sans aucun destinataire si l'écriture des envois échouait (démarrage et liste des envois dans une même transaction) ; certains départs prévus n'étaient jamais enregistrés (date avant l'arrivée, changement de chambre) ; « Changer la date » pouvait enregistrer le départ tout de suite (le formulaire part de la date prévue) ; titre de la page des messages cassé ; relance trop tardive, impossible à annuler, ou sur un ancien canal ; tâches empilées quand le *worker* est arrêté ; SMS non configuré non signalé ; date saisie sans « Programmer » ignorée ; un brouillon confirmé dans un autre onglet pouvait redevenir brouillon. 581 tests.

#### T22 Réponse Présent ou Absent
- **Docs** : [signature cryptographique](https://docs.djangoproject.com/en/6.1/topics/signing/).
- [ ] Lien personnel signé dans le SMS
- [ ] Réponse en un geste dans l'appli
- [ ] Décompte des réponses côté équipe

#### T23 Boîte de réception du résident
- **Maquette** : R2.
- [ ] Filtres : tous, visites, annonces, votes, pour moi
- [ ] Non lu et lu

#### T24 Statuts de livraison des SMS
- [ ] Réception des accusés du fournisseur
- [ ] Liste des échecs sur la campagne

### E5 Votes

#### T25 Sondages anonymes
- **Maquette** : R2.
- [ ] Tables `Participation` et `Vote` séparées : on sait qui a voté, pas pour quoi
- [ ] Date de clôture, résultats pour l'équipe
- [ ] Rappel aux seuls non-votants

### E6 Rendez-vous

#### T26 Disponibilités des éducateurs
- **Maquette** : P4.
- [ ] Grille hebdomadaire, créneaux répétés chaque semaine
- [ ] Réglages : durée, délai minimum

#### T27 Réservation d'un rendez-vous
- **Maquette** : R5.
- [ ] Choix de l'éducateur (nom visible) ou « le premier libre »
- [ ] Prochain créneau libre mis en avant
- [ ] Pas de double réservation (transaction et contrainte)
- [ ] Motif facultatif, visible par l'éducateur seul

#### T28 Messages directs avec un éducateur
- [ ] Conversation résident et éducateur, non lus
- [ ] Heures de réponse affichées

#### T29 Rappels et annulation de rendez-vous
- [ ] Rappel la veille et une heure avant
- [ ] Annulation par le résident ou l'éducateur, avec notification

### E7 Signalements

#### T30 Signaler un problème
- **Maquette** : R3.
- [ ] Catégorie, description, photos, urgence, accès à la chambre
- [ ] Rappel du numéro à appeler pour les urgences graves
- [ ] Photos réduites et sans métadonnées de localisation

#### T31 Tableau des signalements (équipe)
- **Maquette** : P3.
- [ ] Colonnes : nouveau, pris en charge, planifié, fait
- [ ] Assignation, planification d'un créneau
- [ ] Le résident est notifié à chaque changement

#### T32 Délais, relances et récapitulatif quotidien
- [ ] Échéance selon l'urgence : 4 h, 48 h, 7 jours
- [ ] Rappel à l'équipe en cas de retard
- [ ] Récapitulatif chaque matin à 9 h

#### T33 Suivi et confirmation par le résident
- **Maquette** : R4.
- [ ] Historique de la demande
- [ ] « C'est réglé » ou « pas encore » (réouverture)
- [ ] Bouton « relancer » actif 48 h après la dernière mise à jour
- [ ] Clôture automatique 3 jours après « fait »

### E8 Accueils

#### T34 Accueil du résident
- **Maquette** : R1.
- [ ] Action attendue en tête, raccourcis, mes demandes, dernière annonce

#### T35 Tableau de bord de l'équipe
- **Maquette** : P1.
- [ ] Chiffres du jour, éléments en retard, envois programmés
- [ ] Rotation des visites par étage

### E9 Mise en service

#### T36 RGPD
- [ ] Information des résidents (règlement intérieur ou page dédiée)
- [ ] Durées de conservation et suppression des données après le départ
- [ ] Registre des traitements

#### T37 Sécurité avant la mise en ligne
- **Docs** : [sécurité dans Django](https://docs.djangoproject.com/en/6.1/topics/security/), [CSP dans Django](https://docs.djangoproject.com/en/6.1/howto/csp/).
- [ ] `check --deploy` sans alerte, dont HSTS sur les sous-domaines et préchargement (W005, W021) une fois le domaine choisi
- [ ] HTTPS, cookies sécurisés, politique de sécurité du contenu (CSP)
- [ ] Sauvegardes testées

#### T38 Déploiement
- **Docs** : [déployer Django](https://docs.djangoproject.com/en/6.1/howto/deployment/).
- [ ] Adresse réelle du client derrière le proxy (journal d'audit, limites de connexion de T14) et cache partagé pour ces limites
- [ ] Serveur, PostgreSQL, serveur d'application, worker de tâches, tâche périodique
- [ ] Fichiers statiques et médias

#### T39 Essai pilote sur un étage
- [ ] Un étage pendant deux semaines, retours de l'équipe et des résidents
- [ ] Corrections

#### T40 Guides d'utilisation
- [ ] Guide de l'équipe et guide du résident

### E10 Phase 2

#### T41 Discussion entre résidents et modération
- [ ] Salons, messages, signalement d'un message
- [ ] Rôle modérateur donné par l'équipe (personnel ou résidents désignés)
- [ ] Masquer un message, mettre un résident en pause
