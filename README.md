# HJB Résidence

Application web de la résidence Habitat Jeunes Belfort.

Elle permet à l'équipe de prévenir les résidents (visites de logement, maintenance, annonces, votes) par notification ou par SMS. Les résidents peuvent aussi prendre rendez-vous avec un éducateur, signaler un problème dans leur logement et consulter leur accès wifi.

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

Le dépôt est public. Un second workflow lance [gitleaks](https://github.com/gitleaks/gitleaks-action) sur chaque push. Les secrets restent dans l'environnement du serveur (voir [.env.example](.env.example)), jamais dans le dépôt.

## Documentation

Le déploiement, l'exploitation du serveur et le suivi du projet sont documentés hors du dépôt.

## Conventions

- Le code est en anglais : noms, commentaires et tests. Les textes affichés et les adresses visibles restent en français.
- Une branche locale `feat/tXX-nom-court` par tâche, fusionnée dans `develop`.
- Messages de commit au format [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/#specification).
