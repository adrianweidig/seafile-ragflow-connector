#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_ENV="${ENTERPRISE_OUTPUT_ENV:-$ROOT_DIR/connector.env}"
OUTPUT_DIR="${ENTERPRISE_OUTPUT_DIR:-$ROOT_DIR/output/enterprise-compose}"
NON_INTERACTIVE="${ENTERPRISE_NONINTERACTIVE:-false}"
ASSUME_YES="${ENTERPRISE_ASSUME_YES:-false}"
RUN_CONFIG_CHECK="${ENTERPRISE_RUN_CONFIG_CHECK:-true}"
RUN_UP="${ENTERPRISE_RUN_UP:-false}"

usage() {
  cat <<'USAGE'
Enterprise Compose Schnellkonfiguration für Seafile RAGFlow Connector.

Interaktiv:
  bash scripts/configure-enterprise-compose.sh

Nicht interaktiv, z. B. für Automatisierung:
  ENTERPRISE_NONINTERACTIVE=true \
  ENTERPRISE_ASSUME_YES=true \
  ENTERPRISE_MODE=external \
  ENTERPRISE_STATE_MODE=bundled \
  ENTERPRISE_WITH_SEARCH=true \
  ENTERPRISE_WITH_OPENWEBUI=true \
  ENTERPRISE_CA_HOST_FILE=/etc/pki/company-root-ca.pem \
  ENTERPRISE_SEAFILE_BASE_URL=https://seafile.intern \
  ENTERPRISE_SEAFILE_PUBLIC_BASE_URL=https://seafile.intern \
  ENTERPRISE_RAGFLOW_BASE_URL=https://ragflow-api.intern \
  ENTERPRISE_OPENWEBUI_BASE_URL=https://openwebui.intern \
  ENTERPRISE_CONNECTOR_PUBLIC_BASE_URL=https://connector.intern \
  bash scripts/configure-enterprise-compose.sh

Secrets werden dabei aus bereits exportierten Prozessvariablen gelesen:
  SEAFILE_ADMIN_TOKEN
  SEAFILE_SYNC_USER_TOKEN
  RAGFLOW_API_KEY
  RAGFLOW_INTERACTIVE_API_KEY       # optionaler Key des Admin-Zielusers
  AUTHZ_API_SHARED_SECRET
  POSTGRES_PASSWORD                 # nur bei ENTERPRISE_STATE_MODE=bundled
  DATABASE_URL und REDIS_URL        # nur bei ENTERPRISE_STATE_MODE=external
  OPENWEBUI_ADMIN_API_KEY

ENTERPRISE_CA_HOST_FILE ist optional. Wenn der Pfad unbekannt ist, startet der
Stack mit den System-CAs; die Unternehmens-CA kann später ergänzt werden.

Optionen:
  --output-env PATH      Ziel für connector.env, Default: ./connector.env
  --output-dir PATH      Ziel für Startskripte, Default: ./output/enterprise-compose
  --non-interactive      Keine Rückfragen, fehlende Pflichtwerte führen zu Fehlern
  --assume-yes           Bestehende Ausgabedateien mit Backup überschreiben
  --no-config-check      Docker-Compose-Konfigurationscheck nicht ausführen
  --up                   Nach erfolgreicher Konfiguration direkt starten
  -h, --help             Hilfe anzeigen
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --output-env)
      mkdir -p "$(dirname "$2")"
      OUTPUT_ENV="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="$(mkdir -p "$2" && cd "$2" && pwd)"
      shift 2
      ;;
    --non-interactive)
      NON_INTERACTIVE=true
      shift
      ;;
    --assume-yes)
      ASSUME_YES=true
      shift
      ;;
    --no-config-check)
      RUN_CONFIG_CHECK=false
      shift
      ;;
    --up)
      RUN_UP=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unbekannte Option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

PORTAINER_BUNDLE="${ENTERPRISE_PORTAINER_BUNDLE:-true}"
PORTAINER_COMPOSE_FILE="${ENTERPRISE_PORTAINER_COMPOSE_FILE:-$OUTPUT_DIR/portainer-compose.yml}"
PORTAINER_ENV_FILE="${ENTERPRISE_PORTAINER_ENV_FILE:-$OUTPUT_DIR/portainer.env}"

is_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|y|Y|ja|JA|j|J|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

die() {
  printf 'FEHLER: %s\n' "$*" >&2
  exit 1
}

note() {
  printf '%s\n' "$*"
}

random_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 24
    return
  fi
  LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 48
  printf '\n'
}

current_version_image() {
  local version
  version="$(awk -F '"' '/^version = / {print $2; exit}' "$ROOT_DIR/pyproject.toml" 2>/dev/null || true)"
  if [ -n "$version" ]; then
    printf 'ghcr.io/adrianweidig/seafile-ragflow-connector:%s\n' "$version"
  else
    printf 'ghcr.io/adrianweidig/seafile-ragflow-connector:latest\n'
  fi
}

normalize_path() {
  local raw="$1"
  if [[ "$raw" =~ ^[A-Za-z]:[\\/] ]]; then
    if command -v wslpath >/dev/null 2>&1; then
      raw="$(wslpath -a "$raw")"
    elif command -v cygpath >/dev/null 2>&1; then
      raw="$(cygpath -u "$raw")"
    fi
  fi
  case "$raw" in
    /*) printf '%s\n' "$raw" ;;
    *) printf '%s\n' "$ROOT_DIR/$raw" ;;
  esac
}

prompt_value() {
  local var_name="$1"
  local label="$2"
  local default_value="${3:-}"
  local required="${4:-false}"
  local value="${!var_name:-}"

  if [ -z "$value" ]; then
    value="$default_value"
  fi

  if is_true "$NON_INTERACTIVE"; then
    if [ -z "$value" ] && is_true "$required"; then
      die "$var_name ist erforderlich"
    fi
    printf -v "$var_name" '%s' "$value"
    return
  fi

  while :; do
    if [ -n "$default_value" ]; then
      read -r -p "$label [$default_value]: " value
      value="${value:-$default_value}"
    else
      read -r -p "$label: " value
    fi
    if [ -n "$value" ] || ! is_true "$required"; then
      printf -v "$var_name" '%s' "$value"
      return
    fi
    note "Pflichtwert, bitte setzen."
  done
}

prompt_secret() {
  local var_name="$1"
  local label="$2"
  local required="${3:-true}"
  local generate_if_empty="${4:-false}"
  local value="${!var_name:-}"

  if is_true "$NON_INTERACTIVE"; then
    if [ -z "$value" ] && is_true "$generate_if_empty"; then
      value="$(random_secret)"
    fi
    if [ -z "$value" ] && is_true "$required"; then
      die "$var_name ist erforderlich"
    fi
    printf -v "$var_name" '%s' "$value"
    return
  fi

  while :; do
    if is_true "$generate_if_empty"; then
      read -r -s -p "$label (leer = automatisch generieren): " value
    else
      read -r -s -p "$label: " value
    fi
    printf '\n'
    if [ -z "$value" ] && is_true "$generate_if_empty"; then
      value="$(random_secret)"
      note "$label wurde automatisch generiert."
    fi
    if [ -n "$value" ] || ! is_true "$required"; then
      printf -v "$var_name" '%s' "$value"
      return
    fi
    note "Pflichtwert, bitte setzen."
  done
}

prompt_yes_no() {
  local var_name="$1"
  local label="$2"
  local default_value="${3:-false}"
  local value="${!var_name:-}"
  local suffix="[j/N]"
  if is_true "$default_value"; then
    suffix="[J/n]"
  fi

  if [ -z "$value" ] && ! is_true "$NON_INTERACTIVE"; then
    read -r -p "$label $suffix: " value
  fi
  if [ -z "$value" ]; then
    value="$default_value"
  fi
  if is_true "$value"; then
    printf -v "$var_name" 'true'
  else
    printf -v "$var_name" 'false'
  fi
}

require_https_url() {
  local name="$1"
  local value="$2"
  case "$value" in
    https://*) ;;
    *) die "$name muss in diesem Enterprise-Pfad mit https:// beginnen" ;;
  esac
}

require_http_url() {
  local name="$1"
  local value="$2"
  case "$value" in
    http://*|https://*) ;;
    *) die "$name muss mit http:// oder https:// beginnen" ;;
  esac
}

validate_ca_bundle() {
  local ca_file="$1"
  [ -f "$ca_file" ] || die "CA-Bundle nicht gefunden: $ca_file"
  if grep -q 'PRIVATE KEY' "$ca_file"; then
    die "CA-Bundle darf keinen privaten Schlüssel enthalten: $ca_file"
  fi
  if ! command -v openssl >/dev/null 2>&1; then
    note "WARNUNG: openssl nicht gefunden, CA-Profil kann nicht geprüft werden."
    return
  fi
  openssl x509 -in "$ca_file" -noout >/dev/null 2>&1 \
    || die "CA-Bundle ist kein lesbares PEM-X.509-Zertifikat: $ca_file"
  local cert_text
  cert_text="$(openssl x509 -in "$ca_file" -noout -text)"
  grep -q 'CA:TRUE' <<<"$cert_text" \
    || die "CA-Bundle ist nicht als CA markiert (Basic Constraints CA:TRUE fehlt): $ca_file"
  grep -q 'Certificate Sign' <<<"$cert_text" \
    || die "CA-Bundle ist nicht für Zertifikatssignatur freigegeben (Key Usage Certificate Sign fehlt): $ca_file"
}

env_quote() {
  local value="$1"
  if [[ "$value" == *$'\n'* ]]; then
    die "Env-Werte dürfen keine Zeilenumbrüche enthalten"
  fi
  if [[ "$value" =~ ^[A-Za-z0-9_./:@%+=,{}#-]*$ ]]; then
    printf '%s' "$value"
    return
  fi
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//\$/\\\$}"
  printf '"%s"' "$value"
}

write_env_line() {
  local key="$1"
  local value="${2:-}"
  printf '%s=' "$key" >>"$OUTPUT_ENV"
  env_quote "$value" >>"$OUTPUT_ENV"
  printf '\n' >>"$OUTPUT_ENV"
}

write_generated_script() {
  local file="$1"
  local action="$2"
  shift 2
  {
    printf '#!/usr/bin/env bash\n'
    printf 'set -Eeuo pipefail\n'
    printf 'cd %q\n' "$ROOT_DIR"
    printf 'docker compose --env-file %q' "$OUTPUT_ENV"
    for compose_file in "$@"; do
      printf ' -f %q' "$compose_file"
    done
    printf ' %s\n' "$action"
  } >"$file"
  chmod +x "$file"
}

write_portainer_script() {
  local file="$1"
  local action="$2"
  {
    printf '#!/usr/bin/env bash\n'
    printf 'set -Eeuo pipefail\n'
    printf 'cd %q\n' "$ROOT_DIR"
    printf 'docker compose --env-file %q -f %q %s\n' \
      "$PORTAINER_ENV_FILE" "$PORTAINER_COMPOSE_FILE" "$action"
  } >"$file"
  chmod +x "$file"
}

assert_portainer_compose_has_no_secrets() {
  local secret_name secret_value
  for secret_name in \
    SEAFILE_ADMIN_TOKEN \
    SEAFILE_SYNC_USER_TOKEN \
    RAGFLOW_API_KEY \
    RAGFLOW_INTERACTIVE_API_KEY \
    AUTHZ_API_SHARED_SECRET \
    OPENWEBUI_ADMIN_API_KEY_VALUE \
    POSTGRES_PASSWORD \
    DATABASE_URL \
    REDIS_URL \
    DASHBOARD_PASSWORD \
    OPENWEBUI_PROXY_SHARED_SECRET_VALUE
  do
    secret_value="${!secret_name:-}"
    if [ "${#secret_value}" -ge 8 ] && grep -F -q "$secret_value" "$PORTAINER_COMPOSE_FILE"; then
      die "Portainer-Compose enthält versehentlich einen Secret-Wert aus $secret_name"
    fi
  done
}

write_portainer_bundle() {
  is_true "$PORTAINER_BUNDLE" || return 0
  mkdir -p "$(dirname "$PORTAINER_COMPOSE_FILE")" "$(dirname "$PORTAINER_ENV_FILE")"
  if [ "$OUTPUT_ENV" != "$PORTAINER_ENV_FILE" ]; then
    cp "$OUTPUT_ENV" "$PORTAINER_ENV_FILE"
  fi
  chmod 600 "$PORTAINER_ENV_FILE"

  command -v docker >/dev/null 2>&1 \
    || die "Docker ist erforderlich, um die Portainer-Compose-Datei zu rendern"
  docker compose version >/dev/null 2>&1 \
    || die "Docker Compose ist erforderlich, um die Portainer-Compose-Datei zu rendern"

  local tmp_file
  local compose_args=()
  local compose_file
  for compose_file in "$@"; do
    compose_args+=("-f" "$compose_file")
  done
  tmp_file="$(mktemp)"
  docker compose --env-file "$PORTAINER_ENV_FILE" "${compose_args[@]}" config --no-interpolate >"$tmp_file"
  {
    printf '# Portainer-ready Compose generated by scripts/configure-enterprise-compose.sh\n'
    printf '# Paste this file into Portainer and import the matching portainer.env values.\n'
    printf '# Secrets stay in the env file; this Compose keeps variable placeholders.\n\n'
    cat "$tmp_file"
  } >"$PORTAINER_COMPOSE_FILE"
  rm -f "$tmp_file"
  sanitize_portainer_compose
  assert_portainer_compose_has_no_secrets
  write_portainer_script "$OUTPUT_DIR/check-portainer-config.sh" "config --quiet"
}

sanitize_portainer_compose() {
  local tmp_file
  local certs_volume_block=false
  local indent
  local source_prefix="${ROOT_DIR}/\${CONNECTOR_ENTERPRISE_CA_HOST_FILE"
  local compose_source_prefix="${ROOT_DIR}/deploy/compose/\${CONNECTOR_ENTERPRISE_CA_HOST_FILE"
  tmp_file="$(mktemp)"
  while IFS= read -r line; do
    line="${line//$compose_source_prefix/\${CONNECTOR_ENTERPRISE_CA_HOST_FILE}"
    line="${line//$source_prefix/\${CONNECTOR_ENTERPRISE_CA_HOST_FILE}"
    if [[ "$line" == *'source: ${CONNECTOR_CERTS_HOST_DIR'* ]]; then
      certs_volume_block=true
    elif is_true "$certs_volume_block" && [[ "$line" =~ ^([[:space:]]*)type:[[:space:]]volume[[:space:]]*$ ]]; then
      indent="${BASH_REMATCH[1]}"
      printf '%stype: bind\n' "$indent"
      continue
    elif is_true "$certs_volume_block" && [[ "$line" =~ ^[[:space:]]*volume:[[:space:]]\{\}[[:space:]]*$ ]]; then
      certs_volume_block=false
      continue
    fi
    printf '%s\n' "$line"
  done <"$PORTAINER_COMPOSE_FILE" >"$tmp_file"
  mv "$tmp_file" "$PORTAINER_COMPOSE_FILE"
}

backup_existing() {
  local file="$1"
  [ -e "$file" ] || return 0
  local backup="${file}.bak.$(date -u +%Y%m%dT%H%M%SZ)"
  if is_true "$ASSUME_YES"; then
    mv "$file" "$backup"
    chmod 600 "$backup"
    note "Vorhandene Datei gesichert: $backup"
    return
  fi
  if is_true "$NON_INTERACTIVE"; then
    die "$file existiert bereits. Setze ENTERPRISE_ASSUME_YES=true oder wähle --assume-yes."
  fi
  local answer
  read -r -p "$file existiert. Mit Backup überschreiben? [j/N]: " answer
  is_true "$answer" || die "Abgebrochen, Datei bleibt unverändert."
  mv "$file" "$backup"
  chmod 600 "$backup"
  note "Vorhandene Datei gesichert: $backup"
}

if ! is_true "$NON_INTERACTIVE"; then
  note "Dieser Assistent erzeugt eine Portainer-fertige Installation."
  note "Du gibst bestehende Seafile-, RAGFlow- und optional OpenWebUI-Ziele an."
  note "Am Ende bekommst du eine einfügbare Compose-Datei plus zugehörige .env-Datei."
  note ""
fi

enterprise_mode="${ENTERPRISE_MODE:-}"
if [ -z "$enterprise_mode" ] && ! is_true "$NON_INTERACTIVE"; then
  note "Betriebsmodus:"
  note "  1) external  - Connector erreicht Seafile/RAGFlow/OpenWebUI über veröffentlichte HTTPS-URLs"
  note "  2) shared    - Connector hängt im bestehenden Docker-Netz und nutzt interne Service-Namen"
  read -r -p "Wie soll der Connector die bestehenden Dienste erreichen? [external]: " enterprise_mode
fi
enterprise_mode="${enterprise_mode:-external}"
case "$enterprise_mode" in
  1|external) enterprise_mode="external" ;;
  2|shared) enterprise_mode="shared" ;;
  *) die "ENTERPRISE_MODE muss external oder shared sein" ;;
esac

ENTERPRISE_WITH_OPENWEBUI="${ENTERPRISE_WITH_OPENWEBUI:-}"
prompt_yes_no ENTERPRISE_WITH_OPENWEBUI "OpenWebUI-Pipes und auditierbare Quellen direkt synchronisieren?" true

ENTERPRISE_WITH_SEARCH="${ENTERPRISE_WITH_SEARCH:-}"
prompt_yes_no ENTERPRISE_WITH_SEARCH "Nutzernahe Search-Webseite als Standardmodul starten?" true

enterprise_state_mode="${ENTERPRISE_STATE_MODE:-}"
if [ -z "$enterprise_state_mode" ] && ! is_true "$NON_INTERACTIVE"; then
  note "Connector-State:"
  note "  1) bundled  - PostgreSQL und Redis laufen im Connector-Stack"
  note "  2) external - vorhandene PostgreSQL-/Redis-Dienste über URLs nutzen"
  read -r -p "Wo soll der Connector-State laufen? [bundled]: " enterprise_state_mode
fi
enterprise_state_mode="${enterprise_state_mode:-bundled}"
case "$enterprise_state_mode" in
  1|bundled) enterprise_state_mode="bundled" ;;
  2|external) enterprise_state_mode="external" ;;
  *) die "ENTERPRISE_STATE_MODE muss bundled oder external sein" ;;
esac

COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-}"
prompt_value COMPOSE_PROJECT_NAME "Compose-Projektname" "seafile-ragflow-connector-enterprise" true

CONNECTOR_IMAGE="${CONNECTOR_IMAGE:-}"
prompt_value CONNECTOR_IMAGE "Connector-Image" "$(current_version_image)" true
CONNECTOR_IMAGE_PULL_POLICY="${CONNECTOR_IMAGE_PULL_POLICY:-missing}"

CA_CONTAINER_FILE="${CONNECTOR_ENTERPRISE_CA_CONTAINER_FILE:-/certs/company-root-ca.pem}"
CA_BUNDLE_VALUE=""
ENTERPRISE_CA_HOST_FILE="${ENTERPRISE_CA_HOST_FILE:-${CONNECTOR_ENTERPRISE_CA_HOST_FILE:-}}"
prompt_value ENTERPRISE_CA_HOST_FILE "Host-Pfad zur Unternehmens-Root-CA/Chain im PEM-Format (leer = nur System-CAs)" "" false
if [ -n "$ENTERPRISE_CA_HOST_FILE" ]; then
  ENTERPRISE_CA_HOST_FILE="$(normalize_path "$ENTERPRISE_CA_HOST_FILE")"
  validate_ca_bundle "$ENTERPRISE_CA_HOST_FILE"
  CONNECTOR_CERTS_HOST_DIR="$(dirname "$ENTERPRISE_CA_HOST_FILE")"
  CA_BUNDLE_VALUE="$CA_CONTAINER_FILE"
else
  CONNECTOR_CERTS_HOST_DIR="${CONNECTOR_CERTS_HOST_DIR:-./certs}"
fi

if [ "$enterprise_mode" = "shared" ]; then
  seafile_base_default="http://seafile"
  seafile_base_label="Wie erreicht der Connector Seafile innerhalb des Docker-Netzwerks? (z. B. http://seafile)"
else
  seafile_base_default=""
  seafile_base_label="Wie erreicht der Connector die Seafile-API außerhalb eines gemeinsamen Docker-Netzwerks? (HTTPS-Reverse-Proxy/LAN)"
fi
ENTERPRISE_SEAFILE_BASE_URL="${ENTERPRISE_SEAFILE_BASE_URL:-${SEAFILE_BASE_URL:-}}"
prompt_value ENTERPRISE_SEAFILE_BASE_URL "$seafile_base_label" "$seafile_base_default" true
if [ "$enterprise_mode" = "external" ]; then
  require_https_url SEAFILE_BASE_URL "$ENTERPRISE_SEAFILE_BASE_URL"
else
  require_http_url SEAFILE_BASE_URL "$ENTERPRISE_SEAFILE_BASE_URL"
fi

if [ "$enterprise_mode" = "shared" ]; then
  seafile_public_default=""
else
  seafile_public_default="$ENTERPRISE_SEAFILE_BASE_URL"
fi
ENTERPRISE_SEAFILE_PUBLIC_BASE_URL="${ENTERPRISE_SEAFILE_PUBLIC_BASE_URL:-${SEAFILE_PUBLIC_BASE_URL:-}}"
prompt_value ENTERPRISE_SEAFILE_PUBLIC_BASE_URL "Wie erreichst du Seafile von extern außerhalb des Docker-Netzwerks? (Browser-/OpenWebUI-Original-Links)" "$seafile_public_default" "$ENTERPRISE_WITH_OPENWEBUI"
if [ -n "$ENTERPRISE_SEAFILE_PUBLIC_BASE_URL" ]; then
  require_http_url SEAFILE_PUBLIC_BASE_URL "$ENTERPRISE_SEAFILE_PUBLIC_BASE_URL"
fi

if [ "$enterprise_mode" = "shared" ]; then
  ragflow_base_default="http://ragflow:9380"
  ragflow_base_label="Wie erreicht der Connector die RAGFlow-API innerhalb desselben Docker-Netzwerks? (z. B. http://ragflow:9380)"
else
  ragflow_base_default=""
  ragflow_base_label="Wie erreicht der Connector die RAGFlow-API außerhalb eines gemeinsamen Docker-Netzwerks? (HTTPS-Reverse-Proxy/LAN)"
fi
ENTERPRISE_RAGFLOW_BASE_URL="${ENTERPRISE_RAGFLOW_BASE_URL:-${RAGFLOW_BASE_URL:-}}"
prompt_value ENTERPRISE_RAGFLOW_BASE_URL "$ragflow_base_label" "$ragflow_base_default" true
if [ "$enterprise_mode" = "external" ]; then
  require_https_url RAGFLOW_BASE_URL "$ENTERPRISE_RAGFLOW_BASE_URL"
else
  require_http_url RAGFLOW_BASE_URL "$ENTERPRISE_RAGFLOW_BASE_URL"
fi

ENTERPRISE_RAGFLOW_PUBLIC_BASE_URL="${ENTERPRISE_RAGFLOW_PUBLIC_BASE_URL:-${RAGFLOW_PUBLIC_BASE_URL:-}}"
if [ "$enterprise_mode" = "shared" ]; then
  ragflow_public_default=""
else
  ragflow_public_default="$ENTERPRISE_RAGFLOW_BASE_URL"
fi
prompt_value ENTERPRISE_RAGFLOW_PUBLIC_BASE_URL "Wie erreichst du RAGFlow im Browser außerhalb des Docker-Netzwerks, falls Quellen direkt zu RAGFlow verlinken sollen?" "$ragflow_public_default" false
if [ -n "$ENTERPRISE_RAGFLOW_PUBLIC_BASE_URL" ]; then
  require_http_url RAGFLOW_PUBLIC_BASE_URL "$ENTERPRISE_RAGFLOW_PUBLIC_BASE_URL"
fi

SEAFILE_ADMIN_TOKEN="${SEAFILE_ADMIN_TOKEN:-}"
prompt_secret SEAFILE_ADMIN_TOKEN "Seafile Admin-Token" true false
SEAFILE_SYNC_USER_TOKEN="${SEAFILE_SYNC_USER_TOKEN:-}"
prompt_secret SEAFILE_SYNC_USER_TOKEN "Seafile Sync-User-Token" true false
SEAFILE_SYNC_USER_EMAIL="${SEAFILE_SYNC_USER_EMAIL:-}"
prompt_value SEAFILE_SYNC_USER_EMAIL "Seafile Sync-User-E-Mail, optional" "" false
SEAFILE_SYNC_USER_AUTO_SHARE_ENABLED="${SEAFILE_SYNC_USER_AUTO_SHARE_ENABLED:-false}"
prompt_yes_no SEAFILE_SYNC_USER_AUTO_SHARE_ENABLED "Fehlenden Zugriff des verifizierten Sync-Users für alle bestehenden und künftigen aktiven geeigneten Bibliotheken als Nur-Lese-Root-Freigabe ergänzen?" false
if is_true "$SEAFILE_SYNC_USER_AUTO_SHARE_ENABLED" && [ -z "$SEAFILE_SYNC_USER_EMAIL" ]; then
  die "SEAFILE_SYNC_USER_EMAIL ist bei aktivierter automatischer Sync-User-Freigabe erforderlich"
fi

RAGFLOW_API_KEY="${RAGFLOW_API_KEY:-}"
prompt_secret RAGFLOW_API_KEY "RAGFlow API-Key" true false
RAGFLOW_INTERACTIVE_API_KEY="${RAGFLOW_INTERACTIVE_API_KEY:-}"
prompt_secret RAGFLOW_INTERACTIVE_API_KEY "Optionaler RAGFlow API-Key des interaktiven Admin-Zielusers" false false
RAGFLOW_INTERACTIVE_OWNER_ID="${RAGFLOW_INTERACTIVE_OWNER_ID:-}"
RAGFLOW_INTERACTIVE_CHAT_MODEL_ID="${RAGFLOW_INTERACTIVE_CHAT_MODEL_ID:-}"
if [ -n "$RAGFLOW_INTERACTIVE_API_KEY" ]; then
  prompt_value RAGFLOW_INTERACTIVE_OWNER_ID "RAGFlow User-ID des interaktiven Admin-Zielusers" "" true
  prompt_value RAGFLOW_INTERACTIVE_CHAT_MODEL_ID "RAGFlow Chat-Modell-ID des interaktiven Admin-Zielusers" "" true
elif [ -n "$RAGFLOW_INTERACTIVE_OWNER_ID" ] || [ -n "$RAGFLOW_INTERACTIVE_CHAT_MODEL_ID" ]; then
  die "RAGFLOW_INTERACTIVE_OWNER_ID und RAGFLOW_INTERACTIVE_CHAT_MODEL_ID dürfen nur zusammen mit RAGFLOW_INTERACTIVE_API_KEY gesetzt werden"
fi

ragflow_dataset_permission_default="me"
if [ -n "$RAGFLOW_INTERACTIVE_API_KEY" ]; then
  ragflow_dataset_permission_default="team"
fi
RAGFLOW_GENERATED_DATASET_PERMISSION="${RAGFLOW_GENERATED_DATASET_PERMISSION:-}"
prompt_value RAGFLOW_GENERATED_DATASET_PERMISSION "Berechtigung neuer RAGFlow-Bibliotheks-Datasets (me oder team)" "$ragflow_dataset_permission_default" true
case "$RAGFLOW_GENERATED_DATASET_PERMISSION" in
  me|team) ;;
  *) die "RAGFLOW_GENERATED_DATASET_PERMISSION muss me oder team sein" ;;
esac
if [ -n "$RAGFLOW_INTERACTIVE_API_KEY" ] && [ "$RAGFLOW_GENERATED_DATASET_PERMISSION" != "team" ]; then
  die "RAGFLOW_GENERATED_DATASET_PERMISSION muss bei gesetztem RAGFLOW_INTERACTIVE_API_KEY team sein"
fi

AUTHZ_API_SHARED_SECRET="${AUTHZ_API_SHARED_SECRET:-}"
prompt_secret AUTHZ_API_SHARED_SECRET "Shared Secret für Authz-API und Search" true true

POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-}"
DATABASE_URL="${DATABASE_URL:-}"
REDIS_URL="${REDIS_URL:-}"
if [ "$enterprise_state_mode" = "bundled" ]; then
  prompt_secret POSTGRES_PASSWORD "Postgres-Passwort für den Connector-State" true true
  DATABASE_URL=""
  REDIS_URL=""
else
  POSTGRES_PASSWORD=""
  prompt_secret DATABASE_URL "Externe PostgreSQL-DATABASE_URL" true false
  prompt_secret REDIS_URL "Externe REDIS_URL" true false
fi

SEARCH_SERVICE_PUBLISHED_PORT="${SEARCH_SERVICE_PUBLISHED_PORT:-}"
if is_true "$ENTERPRISE_WITH_SEARCH"; then
  prompt_value SEARCH_SERVICE_PUBLISHED_PORT "Search-Port-Bindung" "127.0.0.1:18090" true
fi

DASHBOARD_USER="${CONNECTOR_DASHBOARD_AUTH_USERNAME:-admin}"
prompt_value DASHBOARD_USER "Dashboard-Benutzername" "$DASHBOARD_USER" true
DASHBOARD_PASSWORD="${CONNECTOR_DASHBOARD_AUTH_PASSWORD:-}"
prompt_secret DASHBOARD_PASSWORD "Dashboard-Passwort" true true
CONNECTOR_DASHBOARD_PUBLISHED_PORT="${CONNECTOR_DASHBOARD_PUBLISHED_PORT:-}"
prompt_value CONNECTOR_DASHBOARD_PUBLISHED_PORT "Dashboard-Port-Bindung" "127.0.0.1:18080" true
CONNECTOR_DASHBOARD_CONTROL_ENABLED="${CONNECTOR_DASHBOARD_CONTROL_ENABLED:-false}"
prompt_yes_no CONNECTOR_DASHBOARD_CONTROL_ENABLED "Interaktive Dashboard-Administration aktivieren?" false
if [[ -z "${CONNECTOR_AUTOMATION_INITIAL_STATE:-}" ]]; then
  if is_true "$CONNECTOR_DASHBOARD_CONTROL_ENABLED"; then
    CONNECTOR_AUTOMATION_INITIAL_STATE=stopped
  else
    CONNECTOR_AUTOMATION_INITIAL_STATE=running
  fi
fi
case "$CONNECTOR_AUTOMATION_INITIAL_STATE" in
  running|stopped) ;;
  *) die "CONNECTOR_AUTOMATION_INITIAL_STATE muss running oder stopped sein." ;;
esac

SEAFILE_FILE_URL_TEMPLATE="${SEAFILE_FILE_URL_TEMPLATE:-}"
seafile_original_link_base="${ENTERPRISE_SEAFILE_PUBLIC_BASE_URL:-$ENTERPRISE_SEAFILE_BASE_URL}"
default_file_template="${seafile_original_link_base}/lib/{repo_id}/file{path_quoted}{page_fragment}"
if ! is_true "$NON_INTERACTIVE"; then
  note "Standard für Originaldatei-Links: $default_file_template"
fi
prompt_value SEAFILE_FILE_URL_TEMPLATE "Muss die Seafile-Webroute für Originaldateien vom Standard abweichen? (leer = Standard verwenden)" "" false

SEAFILE_REWRITE_DOWNLOAD_URLS="${SEAFILE_REWRITE_DOWNLOAD_URLS:-}"
prompt_yes_no SEAFILE_REWRITE_DOWNLOAD_URLS "Liefert Seafile Download-/Fileserver-Links mit anderem Host, der umgeschrieben werden muss?" false
SEAFILE_DOWNLOAD_REWRITE_FROM="${SEAFILE_DOWNLOAD_REWRITE_FROM:-}"
SEAFILE_DOWNLOAD_REWRITE_TO="${SEAFILE_DOWNLOAD_REWRITE_TO:-}"
if is_true "$SEAFILE_REWRITE_DOWNLOAD_URLS"; then
  prompt_value SEAFILE_DOWNLOAD_REWRITE_FROM "Welche von Seafile erzeugte Download-URL sieht der Connector aktuell? (Prefix, z. B. https://seafile.example/seafhttp)" "" true
  prompt_value SEAFILE_DOWNLOAD_REWRITE_TO "Welche interne URL soll der Connector stattdessen für Downloads nutzen? (Docker-/LAN-Prefix, z. B. http://seafile/seafhttp)" "$ENTERPRISE_SEAFILE_BASE_URL" true
fi

OPENWEBUI_BASE_URL=""
OPENWEBUI_ADMIN_API_KEY_VALUE=""
OPENWEBUI_PROXY_PUBLIC_BASE_URL=""
OPENWEBUI_PROXY_INTERNAL_BASE_URL=""
OPENWEBUI_PROXY_SHARED_SECRET_VALUE=""
OPENWEBUI_PROXY_CA_BUNDLE_VALUE=""
OPENWEBUI_SOURCE_PREVIEW_MODE_VALUE="connector_viewer"
if is_true "$ENTERPRISE_WITH_OPENWEBUI"; then
  if [ "$enterprise_mode" = "shared" ]; then
    openwebui_base_default="http://openwebui:8080"
    openwebui_base_label="Wie erreicht der Connector die OpenWebUI-API innerhalb des Docker-Netzwerks? (z. B. http://openwebui:8080)"
  else
    openwebui_base_default=""
    openwebui_base_label="Wie erreicht der Connector die OpenWebUI-API außerhalb eines gemeinsamen Docker-Netzwerks? (HTTPS-Reverse-Proxy/LAN)"
  fi
  OPENWEBUI_BASE_URL="${ENTERPRISE_OPENWEBUI_BASE_URL:-${OPENWEBUI_BASE_URL:-}}"
  prompt_value OPENWEBUI_BASE_URL "$openwebui_base_label" "$openwebui_base_default" true
  if [ "$enterprise_mode" = "external" ]; then
    require_https_url OPENWEBUI_BASE_URL "$OPENWEBUI_BASE_URL"
  else
    require_http_url OPENWEBUI_BASE_URL "$OPENWEBUI_BASE_URL"
  fi

  OPENWEBUI_ADMIN_API_KEY_VALUE="${OPENWEBUI_ADMIN_API_KEY:-}"
  prompt_secret OPENWEBUI_ADMIN_API_KEY_VALUE "OpenWebUI Admin-API-Key (leer = OpenWebUI-Sync vorbereiten, aber deaktiviert lassen)" false false
  OPENWEBUI_SYNC_MODE_VALUE="${OPENWEBUI_SYNC_MODE:-sync}"
  if [ -z "$OPENWEBUI_ADMIN_API_KEY_VALUE" ]; then
    OPENWEBUI_SYNC_MODE_VALUE="disabled"
    note "OpenWebUI Admin-API-Key fehlt; OpenWebUI-Sync wird deaktiviert und kann später per .env aktiviert werden."
  fi

  OPENWEBUI_PROXY_PUBLIC_BASE_URL="${ENTERPRISE_CONNECTOR_PUBLIC_BASE_URL:-${OPENWEBUI_PROXY_PUBLIC_BASE_URL:-}}"
  if [ -n "$OPENWEBUI_ADMIN_API_KEY_VALUE" ] && [ "$enterprise_mode" != "shared" ]; then
    prompt_value OPENWEBUI_PROXY_PUBLIC_BASE_URL "Wie erreichst du den Connector-Proxy aus dem Browser außerhalb des Docker-Netzwerks? (öffentliche HTTPS-URL für OpenWebUI-Preview-Links)" "" true
    require_https_url OPENWEBUI_PROXY_PUBLIC_BASE_URL "$OPENWEBUI_PROXY_PUBLIC_BASE_URL"
  else
    prompt_value OPENWEBUI_PROXY_PUBLIC_BASE_URL "Wie erreichst du den Connector-Proxy aus dem Browser außerhalb des Docker-Netzwerks? (optional für OpenWebUI-Preview-Links)" "" false
    if [ -n "$OPENWEBUI_PROXY_PUBLIC_BASE_URL" ]; then
      require_http_url OPENWEBUI_PROXY_PUBLIC_BASE_URL "$OPENWEBUI_PROXY_PUBLIC_BASE_URL"
    fi
  fi
  if [ -z "$OPENWEBUI_PROXY_PUBLIC_BASE_URL" ]; then
    OPENWEBUI_SOURCE_PREVIEW_MODE_VALUE="citation_only"
    if [ -n "$OPENWEBUI_ADMIN_API_KEY_VALUE" ]; then
      note "Öffentliche Connector-URL fehlt; OpenWebUI-Sync bleibt aktiv, Quellen nutzen vorerst Citation-Links ohne Connector-Preview."
    fi
  fi

  if [ "$enterprise_mode" = "shared" ]; then
    default_proxy_internal="http://connector-controller:8080"
  else
    default_proxy_internal="$OPENWEBUI_PROXY_PUBLIC_BASE_URL"
  fi
  OPENWEBUI_PROXY_INTERNAL_BASE_URL="${ENTERPRISE_CONNECTOR_INTERNAL_BASE_URL:-${OPENWEBUI_PROXY_INTERNAL_BASE_URL:-}}"
  if [ -n "$OPENWEBUI_ADMIN_API_KEY_VALUE" ]; then
    prompt_value OPENWEBUI_PROXY_INTERNAL_BASE_URL "Wie erreicht die OpenWebUI-Pipe den Connector-Proxy serverseitig? (im Shared-Modus meist http://connector-controller:8080)" "$default_proxy_internal" true
  else
    prompt_value OPENWEBUI_PROXY_INTERNAL_BASE_URL "Wie erreicht die OpenWebUI-Pipe den Connector-Proxy serverseitig? (optional)" "$default_proxy_internal" false
  fi
  if [ -n "$OPENWEBUI_PROXY_INTERNAL_BASE_URL" ]; then
    require_http_url OPENWEBUI_PROXY_INTERNAL_BASE_URL "$OPENWEBUI_PROXY_INTERNAL_BASE_URL"
  fi

  OPENWEBUI_PROXY_SHARED_SECRET_VALUE="${OPENWEBUI_PROXY_SHARED_SECRET:-}"
  prompt_secret OPENWEBUI_PROXY_SHARED_SECRET_VALUE "OpenWebUI-Proxy-Shared-Secret" true true

  case "$OPENWEBUI_PROXY_INTERNAL_BASE_URL" in
    https://*) OPENWEBUI_PROXY_CA_BUNDLE_VALUE="$CA_BUNDLE_VALUE" ;;
    *) OPENWEBUI_PROXY_CA_BUNDLE_VALUE="" ;;
  esac
fi

CONNECTOR_DOCKER_NETWORK_NAME="${CONNECTOR_DOCKER_NETWORK_NAME:-}"
if [ "$enterprise_mode" = "shared" ]; then
  prompt_value CONNECTOR_DOCKER_NETWORK_NAME "In welchem vorhandenen Docker-Netz hängen Seafile, RAGFlow und optional OpenWebUI gemeinsam mit dem Connector?" "seafile-ragflow-connector-net" true
fi

compose_files=()
if [ "$enterprise_mode" = "external" ]; then
  compose_files+=("deploy/compose/external-services.compose.yml")
elif is_true "$ENTERPRISE_WITH_OPENWEBUI"; then
  compose_files+=("deploy/compose/openwebui.compose.yml")
else
  compose_files+=("deploy/compose/shared-network.compose.yml")
fi
if [ "$enterprise_state_mode" = "external" ]; then
  compose_files+=("deploy/compose/external-state.compose.yml")
else
  compose_files+=("deploy/compose/bundled-state.compose.yml")
fi
if is_true "$ENTERPRISE_WITH_SEARCH"; then
  compose_files+=("deploy/compose/search.compose.yml")
fi
if [ -n "$CA_BUNDLE_VALUE" ]; then
  compose_files+=("deploy/compose/enterprise-ca.compose.yml")
fi

CONNECTOR_STARTUP_CHECK_VALUE="${CONNECTOR_STARTUP_CHECK:-${ENTERPRISE_STARTUP_CHECK:-}}"
prompt_value CONNECTOR_STARTUP_CHECK_VALUE "Startup-Check (infra = nur DB/Redis beim Start, live = zusätzlich Seafile/RAGFlow)" "infra" true
case "$CONNECTOR_STARTUP_CHECK_VALUE" in
  infra|live|skip|none|false) ;;
  *) die "CONNECTOR_STARTUP_CHECK muss infra, live, skip, none oder false sein" ;;
esac
CONNECTOR_BOOTSTRAP_CHECK_LIVE_VALUE="${CONNECTOR_BOOTSTRAP_CHECK_LIVE:-}"
if [ -z "$CONNECTOR_BOOTSTRAP_CHECK_LIVE_VALUE" ]; then
  if [ "$CONNECTOR_STARTUP_CHECK_VALUE" = "live" ]; then
    CONNECTOR_BOOTSTRAP_CHECK_LIVE_VALUE=true
  else
    CONNECTOR_BOOTSTRAP_CHECK_LIVE_VALUE=false
  fi
fi

backup_existing "$OUTPUT_ENV"
mkdir -p "$(dirname "$OUTPUT_ENV")" "$OUTPUT_DIR"

{
  printf '# Generated by scripts/configure-enterprise-compose.sh on %s UTC\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '# Contains runtime secrets. Do not commit this file.\n\n'
} >"$OUTPUT_ENV"
chmod 600 "$OUTPUT_ENV"

write_env_line COMPOSE_PROJECT_NAME "$COMPOSE_PROJECT_NAME"
write_env_line TZ "${TZ:-Europe/Berlin}"
write_env_line APP_ENV production
write_env_line CONNECTOR_LANGUAGE "${CONNECTOR_LANGUAGE:-de}"
write_env_line LOG_LEVEL "${LOG_LEVEL:-INFO}"
write_env_line LOG_FORMAT "${LOG_FORMAT:-json}"
write_env_line CONNECTOR_IMAGE "$CONNECTOR_IMAGE"
write_env_line CONNECTOR_IMAGE_PULL_POLICY "$CONNECTOR_IMAGE_PULL_POLICY"
write_env_line POSTGRES_IMAGE "${POSTGRES_IMAGE:-postgres:16}"
write_env_line POSTGRES_IMAGE_PULL_POLICY "${POSTGRES_IMAGE_PULL_POLICY:-missing}"
write_env_line REDIS_IMAGE "${REDIS_IMAGE:-redis:7}"
write_env_line REDIS_IMAGE_PULL_POLICY "${REDIS_IMAGE_PULL_POLICY:-missing}"
write_env_line CONNECTOR_CERTS_HOST_DIR "$CONNECTOR_CERTS_HOST_DIR"
write_env_line CONNECTOR_ENTERPRISE_CA_HOST_FILE "$ENTERPRISE_CA_HOST_FILE"
write_env_line CONNECTOR_ENTERPRISE_CA_CONTAINER_FILE "$CA_CONTAINER_FILE"
write_env_line CONNECTOR_CA_BUNDLE "$CA_BUNDLE_VALUE"
write_env_line CONNECTOR_SYSTEM_CA_BUNDLE "${CONNECTOR_SYSTEM_CA_BUNDLE:-/etc/ssl/certs/ca-certificates.crt}"
write_env_line SSL_CERT_FILE "${SSL_CERT_FILE:-/etc/ssl/certs/ca-certificates.crt}"
write_env_line REQUESTS_CA_BUNDLE "${REQUESTS_CA_BUNDLE:-/etc/ssl/certs/ca-certificates.crt}"

write_env_line CONNECTOR_DASHBOARD_ENABLED true
write_env_line CONNECTOR_DASHBOARD_CONTROL_ENABLED "$CONNECTOR_DASHBOARD_CONTROL_ENABLED"
write_env_line CONNECTOR_AUTOMATION_INITIAL_STATE "$CONNECTOR_AUTOMATION_INITIAL_STATE"
write_env_line CONNECTOR_DASHBOARD_HOST 0.0.0.0
write_env_line CONNECTOR_DASHBOARD_PORT 8080
write_env_line CONNECTOR_DASHBOARD_PUBLISHED_PORT "$CONNECTOR_DASHBOARD_PUBLISHED_PORT"
write_env_line CONNECTOR_DASHBOARD_AUTH_USERNAME "$DASHBOARD_USER"
write_env_line CONNECTOR_DASHBOARD_AUTH_PASSWORD "$DASHBOARD_PASSWORD"

write_env_line AUTHZ_API_ENABLED true
write_env_line AUTHZ_API_SHARED_SECRET "$AUTHZ_API_SHARED_SECRET"

write_env_line SEAFILE_BASE_URL "$ENTERPRISE_SEAFILE_BASE_URL"
write_env_line SEAFILE_PUBLIC_BASE_URL "$ENTERPRISE_SEAFILE_PUBLIC_BASE_URL"
write_env_line SEAFILE_ADMIN_TOKEN "$SEAFILE_ADMIN_TOKEN"
write_env_line SEAFILE_SYNC_USER_TOKEN "$SEAFILE_SYNC_USER_TOKEN"
write_env_line SEAFILE_SYNC_USER_EMAIL "$SEAFILE_SYNC_USER_EMAIL"
write_env_line SEAFILE_SYNC_USER_AUTO_SHARE_ENABLED "$SEAFILE_SYNC_USER_AUTO_SHARE_ENABLED"
write_env_line SEAFILE_VERIFY_SSL true
write_env_line SEAFILE_CA_BUNDLE "$CA_BUNDLE_VALUE"
write_env_line SEAFILE_REWRITE_DOWNLOAD_URLS "$SEAFILE_REWRITE_DOWNLOAD_URLS"
write_env_line SEAFILE_DOWNLOAD_REWRITE_FROM "$SEAFILE_DOWNLOAD_REWRITE_FROM"
write_env_line SEAFILE_DOWNLOAD_REWRITE_TO "$SEAFILE_DOWNLOAD_REWRITE_TO"
write_env_line SEAFILE_FILE_URL_TEMPLATE "$SEAFILE_FILE_URL_TEMPLATE"

write_env_line RAGFLOW_BASE_URL "$ENTERPRISE_RAGFLOW_BASE_URL"
write_env_line RAGFLOW_API_KEY "$RAGFLOW_API_KEY"
write_env_line RAGFLOW_INTERACTIVE_API_KEY "$RAGFLOW_INTERACTIVE_API_KEY"
write_env_line RAGFLOW_INTERACTIVE_OWNER_ID "$RAGFLOW_INTERACTIVE_OWNER_ID"
write_env_line RAGFLOW_INTERACTIVE_CHAT_MODEL_ID "$RAGFLOW_INTERACTIVE_CHAT_MODEL_ID"
write_env_line RAGFLOW_TEMPLATE_DATASET_NAME "${RAGFLOW_TEMPLATE_DATASET_NAME:-connector_template}"
write_env_line RAGFLOW_GENERATED_DATASET_PERMISSION "$RAGFLOW_GENERATED_DATASET_PERMISSION"
write_env_line RAGFLOW_TEMPLATE_REQUIRED "${RAGFLOW_TEMPLATE_REQUIRED:-true}"
write_env_line RAGFLOW_VERIFY_SSL true
write_env_line RAGFLOW_CA_BUNDLE "$CA_BUNDLE_VALUE"
write_env_line RAGFLOW_PUBLIC_BASE_URL "$ENTERPRISE_RAGFLOW_PUBLIC_BASE_URL"

if is_true "$ENTERPRISE_WITH_SEARCH"; then
  write_env_line SEARCH_SERVICE_ENABLED true
  write_env_line SEARCH_SERVICE_PUBLISHED_PORT "$SEARCH_SERVICE_PUBLISHED_PORT"
  write_env_line SEARCH_AUTHZ_BASE_URL "http://connector-controller:8080"
  write_env_line SEARCH_AUTHZ_SHARED_SECRET "$AUTHZ_API_SHARED_SECRET"
  write_env_line SEARCH_RAGFLOW_BASE_URL "$ENTERPRISE_RAGFLOW_BASE_URL"
  write_env_line SEARCH_RAGFLOW_API_KEY "${RAGFLOW_INTERACTIVE_API_KEY:-$RAGFLOW_API_KEY}"
  write_env_line SEARCH_RAGFLOW_VERIFY_SSL true
  write_env_line SEARCH_RAGFLOW_CA_BUNDLE "$CA_BUNDLE_VALUE"
else
  write_env_line SEARCH_SERVICE_ENABLED false
fi

if is_true "$ENTERPRISE_WITH_OPENWEBUI"; then
  write_env_line OPENWEBUI_INTEGRATION_ENABLED true
  write_env_line OPENWEBUI_BASE_URL "$OPENWEBUI_BASE_URL"
  write_env_line OPENWEBUI_ADMIN_API_KEY "$OPENWEBUI_ADMIN_API_KEY_VALUE"
  write_env_line OPENWEBUI_SYNC_ON_STARTUP true
  write_env_line OPENWEBUI_SYNC_MODE "$OPENWEBUI_SYNC_MODE_VALUE"
  write_env_line OPENWEBUI_CREATE_TOOLS true
  write_env_line OPENWEBUI_CREATE_PIPES true
  write_env_line OPENWEBUI_VERIFY_SSL true
  write_env_line OPENWEBUI_CA_BUNDLE "$CA_BUNDLE_VALUE"
  write_env_line OPENWEBUI_FUNCTION_NAMESPACE "${OPENWEBUI_FUNCTION_NAMESPACE:-ragflow}"
  write_env_line OPENWEBUI_SOURCE_PREVIEW_MODE "$OPENWEBUI_SOURCE_PREVIEW_MODE_VALUE"
  write_env_line OPENWEBUI_PROXY_PUBLIC_BASE_URL "$OPENWEBUI_PROXY_PUBLIC_BASE_URL"
  write_env_line OPENWEBUI_PROXY_INTERNAL_BASE_URL "$OPENWEBUI_PROXY_INTERNAL_BASE_URL"
  write_env_line OPENWEBUI_PROXY_SHARED_SECRET "$OPENWEBUI_PROXY_SHARED_SECRET_VALUE"
  write_env_line OPENWEBUI_PROXY_VERIFY_SSL true
  write_env_line OPENWEBUI_PROXY_CA_BUNDLE "$OPENWEBUI_PROXY_CA_BUNDLE_VALUE"
  write_env_line CONNECTOR_PROXY_VERIFY_SSL true
  write_env_line CONNECTOR_PROXY_CA_BUNDLE "$OPENWEBUI_PROXY_CA_BUNDLE_VALUE"
else
  write_env_line OPENWEBUI_INTEGRATION_ENABLED false
  write_env_line OPENWEBUI_SYNC_MODE disabled
fi

write_env_line POSTGRES_DB "${POSTGRES_DB:-seafile_ragflow_sync}"
write_env_line POSTGRES_USER "${POSTGRES_USER:-sync}"
write_env_line POSTGRES_PASSWORD "$POSTGRES_PASSWORD"
write_env_line DATABASE_URL "$DATABASE_URL"
write_env_line REDIS_DB "${REDIS_DB:-0}"
write_env_line REDIS_URL "$REDIS_URL"
write_env_line CONNECTOR_AUTO_INIT_DB true
write_env_line CONNECTOR_STARTUP_CHECK "$CONNECTOR_STARTUP_CHECK_VALUE"
write_env_line CONNECTOR_BOOTSTRAP_CHECK_LIVE "$CONNECTOR_BOOTSTRAP_CHECK_LIVE_VALUE"

if [ "$enterprise_mode" = "shared" ]; then
  write_env_line CONNECTOR_DOCKER_NETWORK_NAME "$CONNECTOR_DOCKER_NETWORK_NAME"
fi

printf '%s\n' "${compose_files[@]}" >"$OUTPUT_DIR/compose-files.txt"
write_generated_script "$OUTPUT_DIR/check-config.sh" "config --quiet" "${compose_files[@]}"
write_generated_script "$OUTPUT_DIR/up.sh" "up -d" "${compose_files[@]}"
write_generated_script "$OUTPUT_DIR/check-live.sh" "run --rm connector-controller connector check-live" "${compose_files[@]}"
write_generated_script "$OUTPUT_DIR/down.sh" "down" "${compose_files[@]}"
write_portainer_bundle "${compose_files[@]}"

note ""
note "Erzeugt:"
note "  Env-Datei: $OUTPUT_ENV"
note "  Startskripte: $OUTPUT_DIR"
if is_true "$PORTAINER_BUNDLE"; then
  note "  Portainer-Env: $PORTAINER_ENV_FILE"
  if [ -f "$PORTAINER_COMPOSE_FILE" ]; then
    note "  Portainer-Compose: $PORTAINER_COMPOSE_FILE"
  fi
fi
note ""
note "Nächste Befehle:"
note "  bash $OUTPUT_DIR/check-config.sh"
if [ -f "$OUTPUT_DIR/check-portainer-config.sh" ]; then
  note "  bash $OUTPUT_DIR/check-portainer-config.sh"
fi
note "  bash $OUTPUT_DIR/up.sh"
note "  bash $OUTPUT_DIR/check-live.sh"

if is_true "$ENTERPRISE_WITH_OPENWEBUI" && [[ "$OPENWEBUI_PROXY_INTERNAL_BASE_URL" == https://* ]]; then
  note ""
  note "Hinweis: Die OpenWebUI-Pipe ruft den Connector per HTTPS auf."
  note "Mounte dieselbe CA im OpenWebUI-Container unter $CA_CONTAINER_FILE,"
  note "oder setze OPENWEBUI_PROXY_INTERNAL_BASE_URL auf eine interne HTTP-Adresse."
fi

if is_true "$RUN_CONFIG_CHECK"; then
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    note ""
    note "Führe docker compose config --quiet aus..."
    bash "$OUTPUT_DIR/check-config.sh"
    note "Compose-Konfiguration ist syntaktisch gültig."
  else
    note ""
    note "Docker Compose nicht gefunden; Konfigurationscheck übersprungen."
  fi
fi

if is_true "$RUN_UP"; then
  note ""
  note "Starte Stack..."
  bash "$OUTPUT_DIR/up.sh"
fi
