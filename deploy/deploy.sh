#!/usr/bin/env bash
# Deployment of the residence app on an Ubuntu server (card T38).
#
#   sudo ./deploy.sh install   first time: everything, from the packages to HTTPS
#   sudo ./deploy.sh update    new code: dependencies, migrations, restart
#   sudo ./deploy.sh status    services, timers, certificate, last errors
#   sudo ./deploy.sh check     test the site from outside, like a visitor
#   sudo ./deploy.sh manage …  a manage.py command, as the app user
#   sudo ./deploy.sh codes     test mode: follow the SMS (codes) in the journal
#
# Settings: deploy/deploy.conf (copy of deploy.conf.example), or
# /etc/hjb/deploy.conf. Each step can run again without harm: what is
# already done is left as it is, and secrets are never replaced.
#
# Stack: Caddy (HTTPS from Let's Encrypt, reverse proxy), Gunicorn, the
# tasks worker, systemd timers, PostgreSQL, Python 3.13 managed by uv.
# Docs read: caddyserver.com/docs (install, automatic-https, reverse_proxy,
# log, request_body), gunicorn.org/deploy, postgresql.org/docs (peer auth,
# createuser, pg_dump), freedesktop.org systemd.timer and systemd.service,
# docs.djangoproject.com/en/6.1/howto/deployment/, docs.astral.sh/uv.

set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Defaults; deploy.conf may change them.
APP_USER="hjb"
APP_HOME="/srv/hjb"
APP_PORT="8000"
REPO_URL="https://github.com/geekabel/HJB.git"
BRANCH="develop"
PYTHON_VERSION="3.13"
DOMAIN=""
ACME_EMAIL=""
BACKUP_DIR="/var/backups/hjb"
BACKUP_KEEP="14"
ENV_DIR="/etc/hjb"
TEST_MODE="0"
DRY_RUN="${DRY_RUN:-0}"

# Derived paths, set by load_config.
APP_DIR="" VENV="" STATIC_ROOT="" MEDIA_ROOT="" ENV_FILE="" PYTHON_DIR=""

# ---------------------------------------------------------------- helpers

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mAttention :\033[0m %s\n' "$*" >&2; }
die() {
	printf '\033[1;31mErreur :\033[0m %s\n' "$*" >&2
	exit 1
}
trap 'die "la commande « ${BASH_COMMAND} » a échoué (ligne ${LINENO})."' ERR

# Run a command, or only show it with DRY_RUN=1.
run() {
	if [[ "${DRY_RUN}" == "1" ]]; then
		printf '   [essai] %s\n' "$*"
	else
		"$@" || die "« $* » a échoué."
	fi
}

# Write a file from standard input, only if its content changes.
# Return 0 if the file changed (so the caller can reload a service).
write_file() { # path mode owner
	local path="$1" mode="$2" owner="$3" new
	new="$(cat)"
	if [[ -f "${path}" ]] && [[ "$(cat "${path}")" == "${new}" ]]; then
		return 1
	fi
	if [[ "${DRY_RUN}" == "1" ]]; then
		printf '   [essai] écrire %s\n' "${path}"
		return 0
	fi
	# Called in "&& ... || true" lists, where bash ignores set -e: each
	# command checks its own result.
	install -d "$(dirname "${path}")" || die "dossier de ${path} impossible à créer."
	printf '%s\n' "${new}" >"${path}" || die "${path} impossible à écrire."
	chmod "${mode}" "${path}" || die "chmod ${path} a échoué."
	chown "${owner}" "${path}" || die "chown ${path} a échoué."
	return 0
}

require_root() {
	[[ "${EUID}" -eq 0 ]] || die "lancez le script avec sudo."
}

load_config() {
	local file
	for file in "${HERE}/deploy.conf" "${ENV_DIR}/deploy.conf"; do
		if [[ -f "${file}" ]]; then
			# shellcheck source=/dev/null
			source "${file}"
			say "Réglages lus dans ${file}"
			break
		fi
	done
	[[ -n "${DOMAIN}" ]] || die "DOMAIN est vide (deploy.conf)."
	[[ "${DOMAIN}" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ ]] ||
		die "DOMAIN doit être un nom de domaine, sans https:// ni / (par exemple hjb.example.org)."
	[[ "${ACME_EMAIL}" =~ ^[^[:space:]@#]+@[^[:space:]@#]+$ ]] || die "ACME_EMAIL n'est pas une adresse e-mail."
	[[ -n "${ACME_EMAIL}" ]] || die "ACME_EMAIL est vide (deploy.conf)."
	[[ "${TEST_MODE}" =~ ^[01]$ ]] || die "TEST_MODE vaut 0 ou 1 (deploy.conf)."
	APP_DIR="${APP_HOME}/app"
	VENV="${APP_HOME}/venv"
	STATIC_ROOT="${APP_HOME}/static"
	MEDIA_ROOT="${APP_HOME}/media"
	ENV_FILE="${ENV_DIR}/env"
	PYTHON_DIR="/opt/${APP_USER}/python"
}

# Run manage.py as the app user, with the production environment.
manage() {
	# shellcheck disable=SC2016  # expanded by the inner bash, on purpose
	run runuser -u "${APP_USER}" -- bash -c \
		'set -a; . "$1"; set +a; cd "$2" && exec "$3/bin/python" manage.py "${@:4}"' \
		manage "${ENV_FILE}" "${APP_DIR}" "${VENV}" "$@"
}

# ---------------------------------------------------------------- steps

install_packages() {
	say "Paquets du système"
	run apt-get update
	run env DEBIAN_FRONTEND=noninteractive apt-get install -y \
		git curl ca-certificates gnupg ufw acl \
		postgresql postgresql-client \
		debian-keyring debian-archive-keyring apt-transport-https
}

# Caddy from its official repository (https://caddyserver.com/docs/install).
install_caddy() {
	if command -v caddy >/dev/null; then
		say "Caddy déjà installé ($(caddy version | cut -d' ' -f1))"
		return
	fi
	say "Caddy"
	local key=/usr/share/keyrings/caddy-stable-archive-keyring.gpg
	local list=/etc/apt/sources.list.d/caddy-stable.list
	run bash -c "curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --yes -o ${key}"
	run bash -c "curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > ${list}"
	run chmod o+r "${key}" "${list}"
	run apt-get update
	run env DEBIAN_FRONTEND=noninteractive apt-get install -y caddy
}

# Python 3.13 with uv: the same version on every server, whatever the
# Ubuntu release (https://docs.astral.sh/uv/guides/install-python/).
install_python() {
	if ! command -v uv >/dev/null; then
		say "uv (gestionnaire de Python)"
		run bash -c "curl -LsSf https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL=/usr/local/bin sh"
	fi
	say "Python ${PYTHON_VERSION}"
	run install -d -m 755 "${PYTHON_DIR}"
	run env UV_PYTHON_INSTALL_DIR="${PYTHON_DIR}" uv python install --no-config "${PYTHON_VERSION}"
}

create_user() {
	if id "${APP_USER}" >/dev/null 2>&1; then
		say "Utilisateur ${APP_USER} déjà là"
	else
		say "Utilisateur système ${APP_USER}"
		run useradd --system --create-home --home-dir "${APP_HOME}" \
			--shell /usr/sbin/nologin "${APP_USER}"
	fi
	run install -d -o "${APP_USER}" -g "${APP_USER}" -m 750 "${APP_HOME}"
	run install -d -o "${APP_USER}" -g "${APP_USER}" -m 755 "${STATIC_ROOT}"
	# Report photos: the app user only (never served by Caddy).
	run install -d -o "${APP_USER}" -g "${APP_USER}" -m 700 "${MEDIA_ROOT}"
	run install -d -o "${APP_USER}" -g "${APP_USER}" -m 700 "${BACKUP_DIR}"
	run install -d -o root -g "${APP_USER}" -m 750 "${ENV_DIR}"
	# Caddy reads the static files: it needs to cross the home folder.
	if [[ "${DRY_RUN}" != "1" ]] && ! setfacl -m "u:caddy:x" "${APP_HOME}" 2>/dev/null; then
		chmod 751 "${APP_HOME}"
	fi
}

# One role and one database, owned by the app user. "Peer" login over
# the Unix socket: no password exists, so none can leak.
# https://www.postgresql.org/docs/current/auth-peer.html
setup_postgres() {
	say "PostgreSQL : rôle et base ${APP_USER}"
	run systemctl enable --now postgresql
	if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${APP_USER}'" | grep -q 1; then
		# CREATEDB: verify_backup --restore makes a throwaway database.
		run runuser -u postgres -- createuser --createdb "${APP_USER}"
	fi
	if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='${APP_USER}'" | grep -q 1; then
		run runuser -u postgres -- createdb -O "${APP_USER}" "${APP_USER}"
	fi
}

fetch_code() {
	say "Code : ${REPO_URL} (${BRANCH})"
	if [[ ! -d "${APP_DIR}/.git" ]]; then
		run runuser -u "${APP_USER}" -- git clone --branch "${BRANCH}" "${REPO_URL}" "${APP_DIR}"
	else
		run runuser -u "${APP_USER}" -- git -C "${APP_DIR}" fetch --prune origin
		# Exactly the published code: a change made by hand on the server goes.
		run runuser -u "${APP_USER}" -- git -C "${APP_DIR}" checkout -q "${BRANCH}"
		run runuser -u "${APP_USER}" -- git -C "${APP_DIR}" reset -q --hard "origin/${BRANCH}"
	fi
	if [[ "${DRY_RUN}" != "1" ]]; then
		say "Version : $(runuser -u "${APP_USER}" -- git -C "${APP_DIR}" log -1 --format='%h %s')"
	fi
}

setup_venv() {
	say "Environnement Python et dépendances"
	if [[ ! -x "${VENV}/bin/python" ]]; then
		run runuser -u "${APP_USER}" -- env UV_PYTHON_INSTALL_DIR="${PYTHON_DIR}" \
			uv venv --no-config --python "${PYTHON_VERSION}" "${VENV}"
	fi
	run runuser -u "${APP_USER}" -- env UV_CACHE_DIR="${APP_HOME}/.cache/uv" \
		uv pip install --no-config --python "${VENV}/bin/python" -r "${APP_DIR}/requirements.txt"
}

# The environment file of every service. Created once with fresh keys;
# a later run only adds a missing line, never replaces one.
write_env() {
	say "Fichier d'environnement ${ENV_FILE}"
	if [[ "${DRY_RUN}" == "1" ]]; then
		printf '   [essai] créer ou compléter %s (clés générées sur place)\n' "${ENV_FILE}"
		return
	fi
	local py="${VENV}/bin/python"
	touch "${ENV_FILE}"
	chown root:"${APP_USER}" "${ENV_FILE}"
	chmod 640 "${ENV_FILE}"
	add_env DJANGO_SETTINGS_MODULE "config.settings.prod"
	add_env DJANGO_SECRET_KEY "$("${py}" -c 'import secrets; print(secrets.token_urlsafe(64))')"
	add_env DJANGO_ALLOWED_HOSTS "${DOMAIN}"
	add_env DJANGO_WEBAUTHN_RP_ID "${DOMAIN}"
	add_env DJANGO_WEBAUTHN_ORIGINS "https://${DOMAIN}"
	add_env DJANGO_SITE_URL "https://${DOMAIN}"
	add_env DJANGO_ADMIN_URL "gestion-$("${py}" -c 'import secrets; print(secrets.token_hex(4))')"
	add_env DJANGO_WIFI_KEYS "$("${py}" -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
	add_env DJANGO_VAPID_PRIVATE_KEY "$(cd "${APP_DIR}" && "${py}" -c 'from push.vapid import new_private_key; print(new_private_key())')"
	add_env DJANGO_VAPID_CONTACT "mailto:${ACME_EMAIL}"
	add_env POSTGRES_DB "${APP_USER}"
	add_env DJANGO_STATIC_ROOT "${STATIC_ROOT}"
	add_env DJANGO_MEDIA_ROOT "${MEDIA_ROOT}"
	add_env DJANGO_SECURE_HSTS_SECONDS "3600"
	# No SMS until the SMSGate phone (or OVHcloud) is filled in: with an
	# empty address, the checks would stop the deployment (sms.E002).
	add_env DJANGO_SMS_PROVIDER "disabled"
	add_env SMSGATE_URL ""
	add_env SMSGATE_TOKEN ""
	add_env SMSGATE_USERNAME ""
	add_env SMSGATE_PASSWORD ""
	warn "Gardez une copie de DJANGO_WIFI_KEYS hors du serveur : sans elle, les mots de passe wifi sont perdus."
}

add_env() { # name value: add the line only if the name is absent
	if ! grep -q "^$1=" "${ENV_FILE}"; then
		printf '%s=%s\n' "$1" "$2" >>"${ENV_FILE}"
	fi
}

set_env() { # name value: replace the line, or add it
	if grep -q "^$1=" "${ENV_FILE}"; then
		run sed -i "s|^$1=.*|$1=$2|" "${ENV_FILE}"
	else
		add_env "$1" "$2"
	fi
}

# TEST_MODE=1: no SMS leaves, the console provider writes them (codes
# included) to the journal; read them with "deploy.sh codes". Back to 0:
# no SMS at all, until SMSGate or OVHcloud is filled in.
sms_mode() {
	local current
	current="$(sed -n 's/^DJANGO_SMS_PROVIDER=//p' "${ENV_FILE}" | tail -n 1)"
	if [[ "${TEST_MODE}" == "1" ]]; then
		[[ "${current}" == "console" ]] || set_env DJANGO_SMS_PROVIDER console
		warn "Mode test : aucun SMS ne part. Pour lire les codes : sudo $0 codes"
	elif [[ "${current}" == "console" ]]; then
		set_env DJANGO_SMS_PROVIDER disabled
		warn "Mode test arrêté : aucun SMS ne part tant que SMSGate ou OVHcloud n'est pas réglé (${ENV_FILE})."
	fi
}

django_setup() {
	say "Django : migrations, cache, fichiers statiques, vérifications"
	manage migrate --noinput
	manage createcachetable
	manage collectstatic --noinput --clear --verbosity 0
	manage check --deploy --fail-level ERROR
}

# Services and timers (systemd). Gunicorn as in gunicorn.org/deploy.
install_units() {
	say "Services systemd"
	local workers changed=0
	workers="$(($(nproc) * 2 + 1))"
	((workers > 5)) && workers=5
	local common
	common="User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${ENV_FILE}
PrivateTmp=true
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=${APP_HOME} ${BACKUP_DIR}"

	write_file /etc/systemd/system/hjb-web.service 644 root:root <<EOF && changed=1 || true
[Unit]
Description=Résidence HJB : site (Gunicorn)
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=notify
${common}
ExecStart=${VENV}/bin/gunicorn config.wsgi --bind 127.0.0.1:${APP_PORT} --workers ${workers} --timeout 60 --error-logfile -
ExecReload=/bin/kill -s HUP \$MAINPID
KillMode=mixed
TimeoutStopSec=30
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

	# The tasks worker: notifications, SMS, e-mails.
	write_file /etc/systemd/system/hjb-worker.service 644 root:root <<EOF && changed=1 || true
[Unit]
Description=Résidence HJB : tâches de fond
After=network.target postgresql.service
Requires=postgresql.service

[Service]
${common}
ExecStart=${VENV}/bin/python manage.py db_worker --no-reload
# Time to finish a sending: a cut one resumes with run_scheduled.
TimeoutStopSec=300
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

	timer_unit minute "run_scheduled" "*-*-* *:*:00" \
		"${VENV}/bin/python manage.py run_scheduled" "${common}" && changed=1 || true
	# "-": a failed step is noted, the next ones still run.
	timer_unit daily "send_wifi_reminders, nettoyage" "*-*-* 10:00:00 Europe/Paris" \
		"-${VENV}/bin/python manage.py send_wifi_reminders
ExecStart=-${VENV}/bin/python manage.py prune_push_subscriptions
ExecStart=-${VENV}/bin/python manage.py prune_db_task_results
ExecStart=-${VENV}/bin/python manage.py clearsessions" "${common}" && changed=1 || true
	timer_unit backup "sauvegarde" "*-*-* 03:15:00 Europe/Paris" \
		"${VENV}/bin/python manage.py backup_data --to ${BACKUP_DIR} --keep ${BACKUP_KEEP}" \
		"${common}" && changed=1 || true
	# Durations of the page "Réglages", validated by the association.
	timer_unit purge "suppression des données anciennes" "*-*-* 04:30:00 Europe/Paris" \
		"${VENV}/bin/python manage.py purge_personal_data --apply" "${common}" && changed=1 || true

	if ((changed)); then
		run systemctl daemon-reload
	fi
	run systemctl enable --now hjb-web.service hjb-worker.service
	run systemctl enable --now hjb-minute.timer hjb-daily.timer hjb-backup.timer hjb-purge.timer
}

timer_unit() { # name description calendar exec common
	local name="$1" what="$2" calendar="$3" exec="$4" common="$5" changed=1
	write_file "/etc/systemd/system/hjb-${name}.service" 644 root:root <<EOF || changed=0
[Unit]
Description=Résidence HJB : ${what}
After=postgresql.service

[Service]
Type=oneshot
${common}
# A stuck run never blocks the next ones for good.
TimeoutStartSec=30min
ExecStart=${exec}
EOF
	write_file "/etc/systemd/system/hjb-${name}.timer" 644 root:root <<EOF && changed=1 || true
[Unit]
Description=Résidence HJB : ${what} (horaire)

[Timer]
OnCalendar=${calendar}
AccuracySec=1s
Persistent=true

[Install]
WantedBy=timers.target
EOF
	if ((changed)); then
		return 0
	fi
	return 1
}

# The site file goes to /etc/caddy/sites/; the main Caddyfile imports it,
# so other sites of the server stay untouched.
setup_caddy() {
	say "Caddy : site ${DOMAIN} et HTTPS"
	run install -d -m 755 /etc/caddy/sites
	run install -d -o caddy -g caddy -m 755 /var/log/caddy
	local site=/etc/caddy/sites/hjb.caddy changed=0
	# The template of the deployed code, not of the clone the script runs from.
	sed -e "s#@DOMAIN@#${DOMAIN}#g" -e "s#@ACME_EMAIL@#${ACME_EMAIL}#g" \
		-e "s#@STATIC_ROOT@#${STATIC_ROOT}#g" -e "s#@APP_PORT@#${APP_PORT}#g" \
		"${APP_DIR}/deploy/templates/hjb.caddy" | write_file "${site}" 644 root:root && changed=1 || true
	local main=/etc/caddy/Caddyfile
	if ! grep -q '^import /etc/caddy/sites/\*.caddy' "${main}" 2>/dev/null; then
		if [[ ! -s "${main}" ]] || grep -q 'easy way to configure your Caddy web server' "${main}"; then
			# Still the welcome page of the package: replaced (a copy is kept).
			[[ -s "${main}" ]] && run cp "${main}" "${main}.origine"
			printf '# Sites of this server, one file each.\nimport /etc/caddy/sites/*.caddy\n' |
				write_file "${main}" 644 root:root || true
			changed=1
		else
			die "${main} contient déjà d'autres sites. Ajoutez-y la ligne « import /etc/caddy/sites/*.caddy » (hors de tout bloc), puis relancez."
		fi
	fi
	# adapt checks the configuration without opening the log files: a
	# "caddy validate" as root would create them as root, unreadable by
	# the caddy service.
	run caddy adapt --config "${main}" --adapter caddyfile >/dev/null
	run chown -R caddy:caddy /var/log/caddy
	if ((changed)); then
		run systemctl reload caddy
	fi
}

# ufw: SSH, HTTP (certificates and redirect), HTTPS, and HTTP/3 (UDP).
setup_firewall() {
	say "Pare-feu (ufw)"
	local ssh_port
	ssh_port="$(sshd -T 2>/dev/null | awk '/^port /{print $2; exit}' || true)"
	run ufw allow "${ssh_port:-22}/tcp"
	run ufw allow 80/tcp
	run ufw allow 443/tcp
	run ufw allow 443/udp
	run ufw --force enable
	warn "Hostinger : ouvrez aussi ${ssh_port:-22}, 80, 443 (TCP) et 443 (UDP) dans le pare-feu du panneau, s'il est actif."
}

restart_app() {
	say "Redémarrage du site et du worker"
	# A restart, not a reload: a reload would keep the old environment file
	# and the old unit (Gunicorn HUP never re-reads EnvironmentFile).
	run systemctl restart hjb-worker.service hjb-web.service
}

# The site seen from outside, like a visitor. Caddy asks for the
# certificate a few seconds after its reload: up to two minutes of tries.
check_site() {
	say "Vérification de https://${DOMAIN}"
	local url="https://${DOMAIN}/connexion/" code="" headers header try
	if [[ "${DRY_RUN}" == "1" ]]; then
		printf '   [essai] curl %s\n' "${url}"
		return 0
	fi
	local here there
	here="$(curl -4 -sS --max-time 10 https://api.ipify.org 2>/dev/null || true)"
	there="$(getent ahostsv4 "${DOMAIN}" | awk '{print $1; exit}')"
	if [[ -z "${there}" ]]; then
		warn "${DOMAIN} n'a pas encore d'adresse (DNS). Ajoutez l'enregistrement A, attendez, puis : sudo $0 check"
		return 1
	fi
	if [[ -n "${here}" && "${here}" != "${there}" ]]; then
		warn "${DOMAIN} pointe vers ${there}, mais ce serveur est ${here}. Corrigez l'enregistrement A."
		return 1
	fi
	for try in $(seq 1 24); do
		code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "${url}" 2>/dev/null || true)"
		[[ "${code}" == "200" ]] && break
		sleep 5
	done
	if [[ "${code}" != "200" ]]; then
		warn "la page de connexion répond ${code:-rien} après ${try} essais (attendu : 200). Voir : journalctl -u caddy -u hjb-web"
		return 1
	fi
	headers="$(curl -sSI --max-time 10 "${url}")"
	for header in strict-transport-security content-security-policy x-frame-options; do
		grep -qi "^${header}:" <<<"${headers}" || {
			warn "en-tête ${header} absent."
			return 1
		}
	done
	code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "http://${DOMAIN}/connexion/" || true)"
	[[ "${code}" == "308" || "${code}" == "301" ]] || warn "HTTP ne redirige pas vers HTTPS (${code})."
	code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "https://${DOMAIN}/static/ui/css/hjb.css" || true)"
	if [[ "${code}" != "200" ]]; then
		warn "les fichiers statiques répondent ${code}."
		return 1
	fi
	say "Le site répond, en HTTPS, avec ses en-têtes de sécurité."
}

# The SMS written by the console provider (test mode): each one starts
# with "--- SMS to <number> ..." and ends with "---".
codes() {
	say "SMS du mode test, en direct (Ctrl+C pour quitter)"
	journalctl -u hjb-web.service -u hjb-worker.service -n 300 -f -o cat --no-pager |
		awk '/^--- SMS to /{on=1} on{print; fflush()} on && /^---$/{on=0}'
}

status() {
	systemctl --no-pager --lines=0 status hjb-web.service hjb-worker.service caddy.service postgresql.service || true
	systemctl --no-pager list-timers 'hjb-*' || true
	say "Dernières erreurs du site"
	journalctl -u hjb-web.service -p warning --since "-1 day" --no-pager -n 20 || true
}

next_steps() {
	cat <<EOF

Prochaines étapes :
  1. SMS : TEST_MODE=1 dans deploy.conf pour lire les codes avec « sudo $0 codes ».
     Sinon, dans ${ENV_FILE}, remplir SMSGATE_URL et SMSGATE_TOKEN (ou
     SMSGATE_USERNAME et SMSGATE_PASSWORD), mettre DJANGO_SMS_PROVIDER=smsgate.
     Puis : sudo $0 update
  2. Charger la résidence :
     sudo cp ${APP_DIR}/deploy/initial-data.example.yaml ${ENV_DIR}/initial-data.yaml   (puis le remplir)
     sudo $0 manage load_initial_data ${ENV_DIR}/initial-data.yaml --dry-run
  3. Code du premier administrateur : sudo $0 manage activation_code <identifiant>
  4. Adresse du site d'administration : ligne DJANGO_ADMIN_URL de ${ENV_FILE}.
EOF
}

# ---------------------------------------------------------------- main

main() {
	local action="${1:-}"
	# A neutral working folder: the app user cannot read /root or a home
	# folder, and uv or git would fail there.
	cd /
	case "${action}" in
	install)
		require_root
		load_config
		install_packages
		install_caddy
		install_python
		create_user
		setup_postgres
		fetch_code
		setup_venv
		write_env
		sms_mode
		django_setup
		install_units
		setup_firewall
		setup_caddy
		restart_app
		check_site || warn "Le site n'est pas encore joignable. Suivez les étapes ci-dessous, puis : sudo $0 check"
		next_steps
		;;
	update)
		require_root
		load_config
		fetch_code
		setup_venv
		sms_mode
		django_setup
		install_units
		setup_caddy
		restart_app
		check_site || exit 1
		;;
	status)
		load_config
		status
		;;
	check)
		load_config
		check_site || exit 1
		;;
	manage)
		require_root
		load_config
		shift
		[[ $# -gt 0 ]] || die "Quelle commande ? Par exemple : sudo $0 manage activation_code <identifiant>"
		manage "$@"
		;;
	codes)
		require_root
		load_config
		codes
		;;
	*)
		sed -n '2,10p' "$0"
		exit 2
		;;
	esac
}

main "$@"
