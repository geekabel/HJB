# HJB Résidence

Application web de la résidence Habitat Jeunes Belfort.

Elle permet à l'équipe de prévenir les résidents (visites de logement, maintenance, annonces, votes) par notification ou par SMS. Les résidents peuvent aussi prendre rendez-vous avec un éducateur, signaler un problème dans leur logement et consulter leur accès wifi.

- Suivi du projet : [KANBAN.md](KANBAN.md)
- Modèle de données : [docs/modele-de-donnees.md](docs/modele-de-donnees.md)

## Prérequis

- Python 3.12 ou plus (développé avec 3.13). Django 6.1 refuse les versions plus anciennes.
- SQLite 3.37 ou plus en local

Vérifier la version de Python :

```sh
python3 --version
```

Si elle est plus ancienne que 3.12 (Ubuntu 22.04 fournit 3.10), pip échoue avec `Could not find a version that satisfies the requirement Django==6.1.3`. Il faut alors installer un Python plus récent, sans toucher à celui du système. Deux façons :

- avec [uv](https://docs.astral.sh/uv/guides/install-python/) : `uv python install 3.13`, puis remplacer `python3.13 -m venv .venv` ci-dessous par `uv venv --python 3.13 .venv` ;
- sur Ubuntu, avec le dépôt [deadsnakes](https://launchpad.net/~deadsnakes/+archive/ubuntu/ppa) : `sudo add-apt-repository ppa:deadsnakes/ppa`, puis `sudo apt install python3.13 python3.13-venv`.

Le fichier `.python-version` indique la version du projet aux outils qui le lisent (uv, pyenv).

## Installation en local

Le travail est sur la branche `develop` (la branche `main` recevra les versions publiées) :

```sh
git clone -b develop https://github.com/geekabel/HJB.git
cd HJB
python3.13 -m venv .venv          # ou python3.12 ; vérifier ensuite : .venv/bin/python --version
source .venv/bin/activate
pip install -r requirements-dev.txt
python manage.py migrate
python manage.py createsuperuser --noinput --username marie --email ""
python manage.py activation_code marie --phone "06 12 34 56 78"
python manage.py runserver
```

Si le dossier `.venv` a été créé avec un Python trop ancien, le supprimer (`rm -rf .venv`) avant de le recréer.

Il n'y a aucun mot de passe : le premier administrateur active son compte comme tout le monde. Ouvrez http://localhost:8000/activer/, saisissez le code affiché, puis le code SMS (en développement, il s'affiche dans la console du serveur). À la dernière étape, choisissez « Utiliser une application de codes » : scannez le code QR avec Google Authenticator, Microsoft Authenticator ou FreeOTP, puis tapez le code à 6 chiffres. Ensuite, connectez-vous sur /connexion/code/ avec votre identifiant et le code de l'application. La clé d'accès reste possible à la place.

En local, pour entrer tout de suite sans créer de clé d'accès :

```sh
python manage.py dev_login marie
```

La commande affiche un lien valable 10 minutes, une seule fois, qui ouvre la session de ce compte (espace équipe compris). Elle ne marche qu'en développement (`DEBUG`) : en production, la commande refuse et le lien répond « page introuvable ». En production, on se connecte avec une clé d'accès, ou, pour l'équipe, avec le code d'une application.

`manage.py` utilise les réglages de développement (`config.settings.dev`) par défaut. L'administration est sur http://localhost:8000/admin/. En production, son adresse vient de `DJANGO_ADMIN_URL`.

## Tests et contrôles

La CI GitHub Actions lance les mêmes contrôles à chaque push sur `main` et `develop`, et à chaque pull request.

```sh
ruff check .              # lint (règles dans pyproject.toml)
ruff format --check .     # mise en forme
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
```

Contrôle avant déploiement, avec les réglages de production :

```sh
DJANGO_SETTINGS_MODULE=config.settings.prod \
DJANGO_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(64))')" \
DJANGO_ALLOWED_HOSTS=exemple.org \
python manage.py check --deploy
```

### Validation W3C

Les tests enregistrent les pages rendues quand `HTML_CAPTURE_DIR` est défini (voir `tools/html_capture.py`). Le Nu Html Checker du W3C valide ensuite ces pages et tous les fichiers CSS du projet. Il faut Java 17 ou plus et Node.js :

```sh
npm install --no-save --prefix ~/.cache/vnu vnu-jar@26.10.12
HTML_CAPTURE_DIR=build/html python manage.py test
python -m tools.validate_w3c --jar ~/.cache/vnu/node_modules/vnu-jar/build/dist/vnu.jar --html build/html
```

### Secrets

Le dépôt est public. Un second workflow lance [gitleaks](https://github.com/gitleaks/gitleaks-action) sur chaque push. Les secrets restent dans l'environnement du serveur (voir [.env.example](.env.example)).

### Sécurité

- **Politique de sécurité du contenu (CSP)**, en développement aussi : seuls les fichiers du site peuvent s'exécuter ou se charger. Pas de script ni de style écrit dans la page, pas d'autre origine, pas d'affichage dans un cadre. Une violation apparaît dans la console du navigateur.
- **Permissions-Policy** : caméra, micro, position, paiement, USB et capture d'écran sont coupés. La photo d'un signalement passe par le choix d'un fichier, pas par la caméra.
- **En production** : HTTPS obligatoire, cookies `Secure` avec le préfixe `__Host-`, HSTS d'une heure au départ. Quand HTTPS marche sur le vrai domaine (T38), passer `DJANGO_SECURE_HSTS_SECONDS` à 31536000, puis, si tous les sous-domaines sont en HTTPS, `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=1` et `DJANGO_SECURE_HSTS_PRELOAD=1`. D'ici là, `check --deploy` signale seulement ces deux réglages (W005, W021) et l'absence de fournisseur SMS.
- **Dépendances** : la CI lance `pip-audit` sur `requirements.txt` à chaque push.

## Réglages

| Fichier | Rôle |
|---|---|
| `config/settings/base.py` | Réglages communs |
| `config/settings/dev.py` | Développement : `DEBUG`, SQLite, clé de développement |
| `config/settings/prod.py` | Production : tout vient de l'environnement, voir [.env.example](.env.example) |

Les serveurs WSGI et ASGI utilisent `config.settings.prod` par défaut.

## Clés d'accès (connexion)

Les résidents se connectent avec une clé d'accès (passkey) : Face ID, empreinte ou code du téléphone. L'équipe peut aussi utiliser le code à 6 chiffres d'une application (Google Authenticator, Microsoft Authenticator, FreeOTP), plus simple sur un ordinateur ([django-otp, TOTP](https://django-otp-official.readthedocs.io/en/stable/overview.html#totp-devices)). Il n'y a pas de mot de passe, ni pour les résidents ni pour le personnel. Un membre du personnel reçoit son premier code d'un administrateur (action « Générer un code d'activation (personnel) » dans l'administration). La bibliothèque est [django-otp-webauthn](https://django-otp-webauthn.readthedocs.io/en/stable/).

- En développement, ouvrir **http://localhost:8000**, pas http://127.0.0.1:8000 : les navigateurs refusent les clés d'accès sur une adresse IP.
- En production, `DJANGO_WEBAUTHN_RP_ID` (le domaine) et `DJANGO_WEBAUTHN_ORIGINS` sont obligatoires (voir [.env.example](.env.example)). Changer de domaine ensuite rend toutes les clés inutilisables.
- Téléphone perdu : bouton « Couper l'accès » sur la fiche du résident. Les clés sont supprimées et les sessions fermées. Une clé supprimée dans l'administration ferme aussi les sessions.

## Mots de passe wifi

Les mots de passe wifi des chambres sont chiffrés (Fernet). En production, `DJANGO_WIFI_KEYS` est obligatoire : sans lui, l'application refuse de démarrer (voir [.env.example](.env.example)). Gardez une copie de la clé hors du serveur : sans elle, les mots de passe enregistrés sont perdus. Pour changer de clé, mettez la nouvelle en premier dans `DJANGO_WIFI_KEYS`, lancez `python manage.py rotate_wifi_keys`, puis retirez l'ancienne. En développement, une clé est dérivée de la clé secrète de développement.

Le format des identifiants et mots de passe générés (6 et 6 caractères par défaut, comme le portail de la résidence) se change dans l'administration, page « Réglages wifi ». La liste déjà tenue par l'équipe s'importe depuis la liste des résidents, bouton « Importer la liste wifi ».

## Application installable

Le site s'installe sur l'écran d'accueil (manifeste et service worker, voir `ui/pwa.py`). Le service worker ne garde que des fichiers publics. Après un changement du logo, redessinez les icônes avec `python -m tools.make_icons`.

## Notifications

Les notifications Web Push sont signées avec une clé VAPID. En production, `DJANGO_VAPID_PRIVATE_KEY` et `DJANGO_VAPID_CONTACT` sont obligatoires : créez la clé avec `python manage.py vapid_key` et gardez-la secrète. En changer oblige chaque appareil à réactiver les notifications. Sur iPhone, les notifications demandent l'application installée sur l'écran d'accueil. `python manage.py prune_push_subscriptions` retire les appareils des comptes désactivés.

## Tâches de fond et tâches planifiées

Les SMS des messages qui demandent une réponse finissent par un lien personnel vers le site : en production, réglez `DJANGO_SITE_URL` (par défaut, la première adresse de `DJANGO_WEBAUTHN_ORIGINS`).

Les envois de messages passent par le [framework de tâches de Django](https://docs.djangoproject.com/en/6.1/topics/tasks/). En production, les tâches sont gardées dans la base de données par [django-tasks-db](https://github.com/RealOrangeOne/django-tasks-db) et exécutées par son *worker*, un service à part qui tourne en permanence :

```sh
DJANGO_SETTINGS_MODULE=config.settings.prod .venv/bin/python manage.py db_worker --no-reload
```

En développement et dans les tests, les tâches s'exécutent tout de suite, dans la requête.

Pour le service du *worker* :

- le relancer à chaque déploiement : il garde l'ancien code tant qu'il tourne ;
- ajouter `--no-reload` (le rechargement automatique suit `DEBUG` et n'est pas fait pour la production) ;
- lui laisser le temps de finir un envoi à l'arrêt (systemd : `TimeoutStopSec=300`). Un envoi coupé en plein milieu reprend tout seul avec `run_scheduled`, sans renvoyer ce qui est déjà parti.

En production avec SQLite, trois processus écrivent dans la base (le site, le *worker* et `run_scheduled`) : `config/settings/prod.py` active le mode WAL, les transactions `IMMEDIATE` et une attente de 20 secondes sur le verrou.

Les commandes planifiées, avec les réglages de production et les mêmes variables d'environnement que le site (sinon elles prennent les réglages de développement et une mauvaise clé VAPID) :

- chaque minute, `run_scheduled` : lance les messages et les relances arrivés à l'heure, reprend les envois interrompus, enregistre les départs prévus (le jour venu, à midi), demande à SMSGate les accusés de réception des SMS (voir plus bas) envoie les rappels de rendez-vous (la veille entre 18 h et 21 h, et une heure avant), prévient l'équipe d'un signalement en retard et envoie le récapitulatif des signalements (à 9 h, du lundi au vendredi) ;
- chaque jour vers 10 h, heure de Paris, `send_wifi_reminders` : rappel aux résidents 15 jours avant la fin de leur accès wifi ;
- chaque jour, `prune_push_subscriptions` : retire les appareils des comptes désactivés ;
- chaque jour, `prune_db_task_results` : efface les tâches terminées depuis plus de 14 jours ;
- chaque jour, `clearsessions` (Django) : efface les sessions expirées ;
- chaque nuit, `backup_data --to /var/backups/hjb --keep 14` : sauvegarde la base et les photos, puis relit la sauvegarde (voir « Sauvegardes ») ;
- chaque jour, `purge_personal_data --apply` : supprime les données dont la durée de conservation est passée (voir « Données personnelles »). **À ajouter seulement quand l'association a validé les durées.** Sans `--apply`, la commande compte sans rien supprimer.

Exemple de lignes cron, avec le fichier d'environnement du service et `flock` pour qu'une exécution ne commence pas avant la fin de la précédente :

```sh
* * * * * cd /srv/hjb && set -a && . /etc/hjb/env && set +a && DJANGO_SETTINGS_MODULE=config.settings.prod flock -n /tmp/hjb-minute.lock .venv/bin/python manage.py run_scheduled
0 10 * * * cd /srv/hjb && set -a && . /etc/hjb/env && set +a && DJANGO_SETTINGS_MODULE=config.settings.prod flock -n /tmp/hjb-daily.lock sh -c '.venv/bin/python manage.py send_wifi_reminders && .venv/bin/python manage.py prune_push_subscriptions && .venv/bin/python manage.py prune_db_task_results && .venv/bin/python manage.py clearsessions'
```

Le chemin, le fichier d'environnement et le service du *worker* seront fixés avec le déploiement (T38). Relancer une commande est sans risque : un message ou un rappel déjà envoyé ne repart pas.


## Sauvegardes

```sh
python manage.py backup_data --to /var/backups/hjb --keep 14   # sauvegarde, relit, garde les 14 dernières
python manage.py verify_backup /var/backups/hjb/hjb-20261107-030000
```

Une sauvegarde est un dossier (accès réservé au propriétaire) avec :
- `db.sqlite3` : une copie faite par l'API de sauvegarde de SQLite, cohérente même pendant les écritures ;
- `media.tar.gz` : les photos des signalements ;
- `manifest.json` : le nombre de lignes par table, la liste des photos et l'empreinte SHA-256 des deux fichiers.

`backup_data` relit chaque sauvegarde juste après l'avoir faite : intégrité de la base, nombre de lignes, empreintes, liste des photos. Une sauvegarde ratée sort en erreur, et les anciennes restent.

**Les clés ne sont pas dans la sauvegarde** (`DJANGO_SECRET_KEY`, `DJANGO_WIFI_KEYS`, `DJANGO_VAPID_PRIVATE_KEY`). Gardez-en une copie ailleurs, à part : sans les clés wifi, les mots de passe wifi sauvegardés sont illisibles ; avec elles dans la même sauvegarde, un vol les ouvrirait.

**Copie hors du serveur** : la sauvegarde contient des données personnelles. Chiffrez-la avant de la copier ailleurs (par exemple avec `age` ou `gpg`). Son lieu et sa durée sont à fixer avec le déploiement (T38).

**Restaurer** :
1. arrêter le site, le *worker* et les tâches planifiées ;
2. `python manage.py verify_backup <dossier>` ;
3. remplacer le fichier de la base par `db.sqlite3` de la sauvegarde ;
4. vider `DJANGO_MEDIA_ROOT`, puis `tar -xzf <dossier>/media.tar.gz -C "$DJANGO_MEDIA_ROOT"` ;
5. `python manage.py migrate`, puis `python manage.py check --deploy`, puis relancer les services.

Les tests font une sauvegarde, la relisent et la restaurent. Ils vérifient aussi qu'une sauvegarde modifiée est refusée.

Avec PostgreSQL (si T38 le choisit), la base se sauvegarde avec `pg_dump` ; `backup_data` le dit et s'arrête.

## Données personnelles

La page « Vos données » (`/donnees/`) dit aux résidents ce qui est gardé, combien de temps, et leurs droits. Elle est ouverte à tous, et liée depuis la connexion, l'activation et Mon compte.

Les durées de conservation sont dans `RETENTION_DAYS` (`config/settings/base.py`). La page et la suppression utilisent les mêmes. `DJANGO_PRIVACY_CONTACT` donne l'adresse pour exercer ses droits (vide : « l'accueil de la résidence »).

```sh
python manage.py purge_personal_data            # compte ce qui a passé sa durée
python manage.py purge_personal_data --apply    # le supprime, et le note au journal
```

La première fois, lancez-la sans `--apply` pour voir les nombres. Tout se fait en une transaction : avec SQLite, les autres écritures attendent pendant ce temps. Un compte encore lié à autre chose (par exemple éducateur d'un rendez-vous) est gardé, et le journal le dit.

Le registre des traitements est dans `docs/registre-des-traitements.md`. L'association le complète et le valide.

## Votes anonymes

Un message de type « Vote, avis » porte un vote : la question est son titre, avec 2 à 6 choix et une heure de clôture. Les résidents votent dans l'application ou par le lien personnel du SMS. L'équipe voit qui a voté, jamais pour quoi : aucune ligne n'est créée par vote (chaque choix garde un compteur), les commentaires n'ont ni nom, ni date, ni ordre, et la participation ne garde que le jour. Les résultats et les commentaires s'affichent après la clôture, et seulement à partir de 3 votants : avant, voir les voix arriver une à une permettrait de deviner les choix. La relance, si elle est cochée, part 24 h avant la clôture vers ceux qui n'ont pas voté, entre 9 h et 20 h (plus tôt si besoin, jamais la nuit).

Les aperçus du composeur et les essais (« M'envoyer un test ») contiennent un lien de même longueur qui ne marche pas : personne dans l'équipe ne peut répondre ni voter à la place d'un résident.

Limites connues :

- si tous les votants font le même choix, ce choix est connu : c'est inévitable avec un total ;
- quelqu'un qui a accès au serveur peut retrouver un choix en comparant deux copies de la base (ou deux sauvegardes) entre lesquelles une seule personne a voté. Un vote écrit toutes les lignes du sondage à la fois, et ne garde que le jour : la base seule ne dit ni qui a voté quoi, ni à quelle heure. Les journaux du serveur web gardent l'heure des requêtes : les garder peu de temps.

## Envoi de SMS

Le fournisseur se choisit avec `DJANGO_SMS_PROVIDER` (voir [.env.example](.env.example)) :

| Valeur | Usage |
|---|---|
| *(vide)* ou `disabled` | En production : aucun SMS ne part, et rien n'est écrit dans les journaux |
| `console` | Par défaut en développement. Le SMS s'affiche dans la console, rien n'est envoyé. Jamais en production : numéros et codes finiraient dans les journaux |
| `smsgate` | Essais réels avec un téléphone Android et l'application [SMSGate](https://docs.sms-gate.app) |
| `ovh` | Production, avec l'[API SMS d'OVHcloud](https://docs.ovhcloud.com/fr/guides/web-cloud/messaging/sms/sending-via-api-c.md) |

Pour vérifier un réglage, envoyer un SMS d'essai :

```sh
python manage.py send_test_sms "06 12 34 56 78" "Bonjour, ceci est un essai."
```

`python manage.py check` signale une option manquante. Pendant les tests, aucun vrai SMS ne part : le lanceur de tests remplace le fournisseur par une boîte en mémoire.

### Accusés de réception

La page de suivi d'un message dit, pour chaque SMS, s'il est « en route », « reçu », « non reçu » ou « inconnu », et liste les personnes à prévenir autrement. Sans nouvelle après 48 h, l'état passe à « inconnu ».

- **SMSGate** : rien à régler. `run_scheduled` demande l'état des SMS en route : toutes les 5 minutes la première heure, puis toutes les 30 minutes, puis toutes les 2 heures (et encore une semaine après « inconnu », si le téléphone était éteint). 20 SMS et 20 secondes au plus par minute, pour ne pas retarder les envois. Le site doit pouvoir joindre l'adresse `SMSGATE_URL`.
- **OVHcloud** : OVHcloud appelle le site à chaque changement d'état. Ce rappel se règle sur un utilisateur API SMS, donc les SMS passent par cet utilisateur (`OVH_SMS_USER`, droit `POST /sms/*/users/*/jobs`). Choisir un secret long (`DJANGO_SMS_RECEIPT_SECRET`, voir [.env.example](.env.example)), puis, dans l'espace client OVHcloud, rubrique SMS, « Utilisateurs API », menu `...` de l'utilisateur, « Callback », saisir `https://<adresse du site>/sms/ovh/<secret>/` ([guide OVHcloud](https://docs.ovhcloud.com/en/guides/web-cloud/messaging/sms/sms-users)). L'appel d'OVHcloud n'est pas signé : le secret dans l'adresse est la seule protection. Il apparaît dans les journaux du serveur web, comme les liens de réponse : garder ces journaux peu de temps. Sans secret ou sans utilisateur, `check --deploy` le signale et les SMS n'attendent pas d'accusé.

À vérifier au premier essai réel avec OVHcloud : que l'envoi par l'utilisateur API est accepté, que le rappel arrive, et que l'identifiant reçu est bien celui rendu à l'envoi (la documentation ne le dit pas). Sinon, les SMS resteront « en route » puis « inconnu » après 48 h. Un code OVHcloud absent de la liste publiée reste « en route » : seuls les échecs connus sont « non reçu ».

## Conventions

- Le code est en anglais : noms, commentaires et tests. Les textes affichés et les adresses visibles restent en français. Le [glossaire](docs/glossaire.md) relie les mots du métier aux noms du code.

- Une branche locale `feat/tXX-nom-court` par tâche, fusionnée dans `develop`.
- Messages de commit au format [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/#specification).
