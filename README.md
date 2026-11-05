# HJB Résidence

Application web de la résidence Habitat Jeunes Belfort.

Elle permet à l'équipe de prévenir les résidents (visites de logement, maintenance, annonces, votes) par notification ou par SMS. Les résidents peuvent aussi prendre rendez-vous avec un éducateur, signaler un problème dans leur logement et consulter leur accès wifi.

- Suivi du projet : [KANBAN.md](KANBAN.md)
- Modèle de données : [docs/modele-de-donnees.md](docs/modele-de-donnees.md)

## Prérequis

- Python 3.12 ou plus (développé avec 3.13)
- SQLite 3.37 ou plus en local

## Installation en local

```sh
git clone https://github.com/geekabel/HJB.git
cd HJB
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python manage.py migrate
python manage.py createsuperuser --noinput --username marie --email ""
python manage.py activation_code marie --phone "06 12 34 56 78"
python manage.py runserver
```

Il n'y a aucun mot de passe : le premier administrateur active son compte comme tout le monde. Ouvrez http://localhost:8000/activer/, saisissez le code affiché, puis le code SMS (en développement, il s'affiche dans la console du serveur), et créez votre clé d'accès.

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

## Réglages

| Fichier | Rôle |
|---|---|
| `config/settings/base.py` | Réglages communs |
| `config/settings/dev.py` | Développement : `DEBUG`, SQLite, clé de développement |
| `config/settings/prod.py` | Production : tout vient de l'environnement, voir [.env.example](.env.example) |

Les serveurs WSGI et ASGI utilisent `config.settings.prod` par défaut.

## Clés d'accès (connexion)

Tout le monde se connecte avec une clé d'accès (passkey) : Face ID, empreinte ou code du téléphone. Il n'y a pas de mot de passe, ni pour les résidents ni pour le personnel. Un membre du personnel reçoit son premier code d'un administrateur (action « Générer un code d'activation (personnel) » dans l'administration). La bibliothèque est [django-otp-webauthn](https://django-otp-webauthn.readthedocs.io/en/stable/).

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

Trois commandes planifiées, avec les réglages de production et les mêmes variables d'environnement que le site (sinon elles prennent les réglages de développement et une mauvaise clé VAPID) :

- chaque minute, `run_scheduled` : lance les messages et les relances arrivés à l'heure, reprend les envois interrompus et enregistre les départs prévus (le jour venu, à midi) ;
- chaque jour vers 10 h, heure de Paris, `send_wifi_reminders` : rappel aux résidents 15 jours avant la fin de leur accès wifi ;
- chaque jour, `prune_push_subscriptions` : retire les appareils des comptes désactivés ;
- chaque jour, `prune_db_task_results` : efface les tâches terminées depuis plus de 14 jours.

Exemple de lignes cron, avec le fichier d'environnement du service et `flock` pour qu'une exécution ne commence pas avant la fin de la précédente :

```sh
* * * * * cd /srv/hjb && set -a && . /etc/hjb/env && set +a && DJANGO_SETTINGS_MODULE=config.settings.prod flock -n /tmp/hjb-minute.lock .venv/bin/python manage.py run_scheduled
0 10 * * * cd /srv/hjb && set -a && . /etc/hjb/env && set +a && DJANGO_SETTINGS_MODULE=config.settings.prod flock -n /tmp/hjb-daily.lock sh -c '.venv/bin/python manage.py send_wifi_reminders && .venv/bin/python manage.py prune_push_subscriptions && .venv/bin/python manage.py prune_db_task_results'
```

Le chemin, le fichier d'environnement et le service du *worker* seront fixés avec le déploiement (T38). Relancer une commande est sans risque : un message ou un rappel déjà envoyé ne repart pas.


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

## Conventions

- Le code est en anglais : noms, commentaires et tests. Les textes affichés et les adresses visibles restent en français. Le [glossaire](docs/glossaire.md) relie les mots du métier aux noms du code.

- Une branche locale `feat/tXX-nom-court` par tâche, fusionnée dans `develop`.
- Messages de commit au format [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/#specification).
