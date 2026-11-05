# Kanban du projet HJB Résidence

Dernière mise à jour : 5 novembre 2026

Ce fichier suit toutes les tâches jusqu'à la mise en service. Après chaque tâche, on déplace sa carte dans « Fait » et on coche ses critères.

- Maquettes UI/UX : canevas « HJB Résidence · maquettes » (12 écrans)
- Tableau visuel : artifact « Kanban HJB Résidence », mis à jour en même temps que ce fichier
- Modèle de données : [docs/modele-de-donnees.md](docs/modele-de-donnees.md)

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
| Tâches en arrière-plan | Framework de tâches de Django + un backend avec worker | Les backends livrés avec Django servent au développement et aux tests seulement. Le backend de production sera choisi en T21, après lecture de sa doc |
| Notifications | Web Push (application web installable, PWA) | Gratuit. Le SMS ne sert que de secours |
| SMS | Couche « fournisseur » interchangeable | Console en développement, SMSGate pour les tests réels, OVHcloud ou Brevo en production |
| Connexion | Code d'activation remis à l'accueil, code SMS, puis clé d'accès (passkey) | Le numéro de chambre n'est pas un secret |
| Front | Gabarits Django, CSS natif, JavaScript léger | Moins de dépendances, validation W3C plus simple |
| Import Excel | openpyxl en lecture seule, avec defusedxml | Lit les .xlsx sans Excel ; defusedxml bloque les fichiers XML piégés |
| API OVHcloud | Bibliothèque officielle python-ovh | Conseillée par OVHcloud : elle signe les requêtes ; pas de cryptographie maison |
| Code QR | segno (pur Python, sans dépendance, BSD) | SVG inséré dans la page, imprimable |

## Tableau

### En cours

| ID | Tâche | Épopée |
|---|---|---|
| | *(vide)* | |

### À faire

| ID | Tâche | Épopée | Dépend de |
|---|---|---|---|
| T13 | Connexion par clé d'accès (passkey) | E2 Connexion | T12 |
| T14 | Sécurité de l'espace équipe | E2 Connexion | T04, T13 |
| T15 | Accès wifi chiffré (équipe) | E3 Wifi | T06, T05 |
| T16 | Écran « Mon wifi » du résident | E3 Wifi | T13, T15 |
| T17 | Rappels d'expiration du wifi | E3 Wifi | T16, T19 |
| T18 | Application installable (PWA) | E4 Messages | T03 |
| T19 | Notifications Web Push | E4 Messages | T18 |
| T20 | Modèles de message et composeur | E4 Messages | T06, T10 |
| T21 | Envoi programmé et relances | E4 Messages | T19, T20 |
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
- [ ] Accès wifi désactivé : à faire en T15, branché sur le signal `depart_enregistre`
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
- [x] `telephone_verifie_le` sur le compte, affiché sur la fiche ; remis à vide si le numéro change (fiche, administration, import)
- [x] Étape 3 : en attendant T13, page « Téléphone vérifié, la clé d'accès arrive bientôt »
- **Notes** : un SMS qui n'a pas pu partir rend son code inutilisable, mais compte dans la limite horaire (pour ne pas épuiser le crédit SMS). Le code n'est jamais dans les journaux (voir T10). Le champ utilise `autocomplete="one-time-code"` : iOS et Android proposent le code reçu. 21 tests.

#### T13 Connexion par clé d'accès (passkey)
- **Docs** : django-otp-webauthn (à lire en entier avant de coder), [MDN Web Authentication API](https://developer.mozilla.org/fr/docs/Web/API/Web_Authentication_API).
- [ ] Création de la clé après la vérification du téléphone
- [ ] Connexion sans mot de passe
- [ ] Récupération : nouveau code d'activation par l'accueil
- [ ] Sessions longues pour les résidents, avec reconnexion demandée pour les actions sensibles
- [ ] Au départ (T09) : supprimer les clés d'accès, via le signal `depart_enregistre`

#### T14 Sécurité de l'espace équipe
- [ ] Espace équipe réservé aux rôles du personnel
- [ ] Clé d'accès obligatoire pour le personnel
- [ ] Adresse de l'administration Django changée
- [ ] Limite de tentatives de connexion

### E3 Wifi

#### T15 Accès wifi chiffré (équipe)
- **Docs** : bibliothèque cryptography (Fernet).
- [ ] Modèle `AccesWifi` : mot de passe chiffré, clé dans une variable d'environnement
- [ ] Saisie ou génération par l'équipe, date d'expiration à un an
- [ ] Affichage réservé aux administrateurs, chaque affichage dans le journal
- [ ] Au départ (T09) : désactiver l'accès wifi de la chambre, via le signal `depart_enregistre`

#### T16 Écran « Mon wifi » du résident
- **Maquette** : R6.
- [ ] Mot de passe masqué, affiché après confirmation par la clé d'accès
- [ ] Boutons « copier », barre de validité

#### T17 Rappels d'expiration du wifi
- [ ] Notification au résident 15 jours avant
- [ ] Liste des renouvellements à faire pour l'équipe

### E4 Messages

#### T18 Application installable (PWA)
- **Docs** : MDN (manifeste d'application web, service workers).
- [ ] Manifeste, icônes (dont `favicon.ico`, absent pour l'instant), service worker
- [ ] Écran d'aide « ajouter à l'écran d'accueil » pour iPhone (nécessaire pour recevoir les notifications)

#### T19 Notifications Web Push
- **Docs** : MDN Push API, pywebpush (ou django-webpush si sa maintenance est confirmée).
- [ ] Clés VAPID, modèle `AbonnementPush`
- [ ] Demande d'autorisation après un geste de l'utilisateur
- [ ] Nettoyage des abonnements expirés

#### T20 Modèles de message et composeur
- **Maquette** : P2.
- [ ] Types : visite, maintenance, annonce, vote, message libre
- [ ] Modèles modifiables avec champs `{prénom}`, `{chambre}`, `{date}`
- [ ] Ciblage par étage, chambre ou personne, avec le décompte « notification / SMS »
- [ ] Version SMS courte, alerte quand un caractère fait passer en UCS-2
- [ ] Bouton « m'envoyer un test »

#### T21 Envoi programmé et relances
- **Docs** : [framework de tâches de Django](https://docs.djangoproject.com/en/6.0/topics/tasks/), doc du backend choisi.
- [ ] Choix du backend de tâches pour la production, après lecture de sa doc
- [ ] Commande périodique qui lance les campagnes arrivées à l'heure
- [ ] Notification push d'abord, SMS seulement sans abonnement push
- [ ] Envois sans doublon (contrainte unique sur `Envoi`)
- [ ] Relance automatique de ceux qui n'ont pas répondu
- [ ] Départ prévu (T09) : saisi à l'avance, enregistré automatiquement le jour venu

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
