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
python manage.py createsuperuser
python manage.py runserver
```

`manage.py` utilise les réglages de développement (`config.settings.dev`) par défaut. L'administration est sur http://127.0.0.1:8000/admin/.

## Tests et contrôles

```sh
python manage.py test
python manage.py check
```

Contrôle avant déploiement, avec les réglages de production :

```sh
DJANGO_SETTINGS_MODULE=config.settings.prod \
DJANGO_SECRET_KEY=une-cle-longue-et-aleatoire \
DJANGO_ALLOWED_HOSTS=exemple.org \
python manage.py check --deploy
```

## Réglages

| Fichier | Rôle |
|---|---|
| `config/settings/base.py` | Réglages communs |
| `config/settings/dev.py` | Développement : `DEBUG`, SQLite, clé de développement |
| `config/settings/prod.py` | Production : tout vient de l'environnement, voir [.env.example](.env.example) |

Les serveurs WSGI et ASGI utilisent `config.settings.prod` par défaut.

## Conventions

- Une branche locale `feat/tXX-nom-court` par tâche, fusionnée dans `develop`.
- Messages de commit au format [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/#specification).
