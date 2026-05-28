#!/bin/sh
set -eu

log() {
  printf '%s\n' "[connector-entrypoint] $*"
}

fail() {
  printf '%s\n' "[connector-entrypoint] ERROR: $*" >&2
  exit 1
}

truthy() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

refresh_system_ca_certificates() {
  if [ "$(id -u)" -ne 0 ]; then
    fail "entrypoint must start as root so update-ca-certificates can run"
  fi
  if ! command -v update-ca-certificates >/dev/null 2>&1; then
    fail "update-ca-certificates is not available in this image"
  fi

  ca_source="${CONNECTOR_CA_BUNDLE:-}"
  if [ -n "$ca_source" ]; then
    if [ ! -f "$ca_source" ]; then
      fail "CA bundle for system trust does not exist: $ca_source"
    fi
    if grep -q 'PRIVATE KEY' "$ca_source"; then
      fail "CA bundle for system trust must not contain a private key: $ca_source"
    fi
    ca_target="${CONNECTOR_SYSTEM_CA_CERT:-/usr/local/share/ca-certificates/connector-enterprise-ca.crt}"
    mkdir -p "$(dirname "$ca_target")"
    cp "$ca_source" "$ca_target"
    chmod 0644 "$ca_target"
  fi

  update-ca-certificates >/dev/null

  system_bundle="${CONNECTOR_SYSTEM_CA_BUNDLE:-/etc/ssl/certs/ca-certificates.crt}"
  if [ -f "$system_bundle" ]; then
    export SSL_CERT_FILE="${SSL_CERT_FILE:-$system_bundle}"
    export REQUESTS_CA_BUNDLE="${REQUESTS_CA_BUNDLE:-$system_bundle}"
  fi
  log "refreshed system CA certificates"
}

drop_privileges_if_needed() {
  if [ "${CONNECTOR_ENTRYPOINT_PRIVILEGED_DONE:-}" = "1" ]; then
    return 0
  fi
  refresh_system_ca_certificates
  export CONNECTOR_ENTRYPOINT_PRIVILEGED_DONE=1

  if [ "$(id -u)" -ne 0 ]; then
    return 0
  fi
  if ! truthy "${CONNECTOR_DROP_PRIVILEGES:-true}"; then
    return 0
  fi
  runtime_user="${CONNECTOR_RUNTIME_USER:-connector}"
  command -v gosu >/dev/null 2>&1 || fail "gosu is required to drop privileges"
  exec gosu "$runtime_user" "$0" "$@"
}

wait_for_infra() {
  max_wait="${CONNECTOR_STARTUP_MAX_WAIT_SECONDS:-180}"
  sleep_seconds="${CONNECTOR_STARTUP_SLEEP_SECONDS:-5}"
  deadline=$(( $(date +%s) + max_wait ))

  while :; do
    if python - <<'PY'
import sys
from sqlalchemy import create_engine, text
from redis import Redis
from seafile_ragflow_connector.config import get_settings

try:
    settings = get_settings()

    engine = create_engine(settings.database_url, pool_pre_ping=True)
    with engine.connect() as connection:
        connection.execute(text("select 1"))

    client = Redis.from_url(settings.redis_url)
    client.ping()
except Exception as exc:
    print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
    raise SystemExit(1)
PY
    then
      log "database and redis are reachable"
      return 0
    fi

    if [ "$(date +%s)" -ge "$deadline" ]; then
      fail "database or redis did not become ready within ${max_wait}s"
    fi
    log "waiting for database and redis"
    sleep "$sleep_seconds"
  done
}

prepare_runtime_dirs() {
  cache_dir="${CACHE_DIR:-/cache}"
  temp_dir="${TEMP_DIR:-${cache_dir}/tmp}"
  if mkdir -p "$cache_dir" "$temp_dir" 2>/dev/null && [ -w "$cache_dir" ] && [ -w "$temp_dir" ]; then
    export CACHE_DIR="$cache_dir"
    export TEMP_DIR="$temp_dir"
    return 0
  fi

  fallback_cache="${CONNECTOR_FALLBACK_CACHE_DIR:-/tmp/seafile-ragflow-connector/cache}"
  fallback_temp="${CONNECTOR_FALLBACK_TEMP_DIR:-${fallback_cache}/tmp}"
  mkdir -p "$fallback_cache" "$fallback_temp" || fail "cannot create fallback runtime directories: $fallback_cache $fallback_temp"
  export CACHE_DIR="$fallback_cache"
  export TEMP_DIR="$fallback_temp"
  log "runtime cache is not writable, using fallback: $CACHE_DIR"
}

run_startup_checks() {
  mode="${CONNECTOR_STARTUP_CHECK:-infra}"
  case "$mode" in
    skip|none|false)
      log "startup checks skipped"
      ;;
    infra)
      wait_for_infra
      ;;
    live)
      wait_for_infra
      connector check-live
      ;;
    *)
      fail "unsupported CONNECTOR_STARTUP_CHECK=$mode"
      ;;
  esac
}

auto_init_db() {
  if truthy "${CONNECTOR_AUTO_INIT_DB:-true}"; then
    connector init-db
  else
    log "automatic database initialization disabled"
  fi
}

if [ "${1:-}" = "connector" ]; then
  shift
fi

if [ "$#" -eq 0 ]; then
  set -- controller
fi

drop_privileges_if_needed "$@"

case "${1:-}" in
  check-config|--help|-h|help)
    exec connector "$@"
    ;;
  bootstrap)
    prepare_runtime_dirs
    run_startup_checks
    auto_init_db
    if truthy "${CONNECTOR_BOOTSTRAP_CHECK_LIVE:-false}"; then
      connector check-live
    fi
    log "bootstrap completed"
    exit 0
    ;;
  init-db)
    prepare_runtime_dirs
    wait_for_infra
    exec connector "$@"
    ;;
  check-live|sync-once|cleanup-orphans|openwebui-sync-once|controller|worker|reconciler|dashboard)
    prepare_runtime_dirs
    run_startup_checks
    auto_init_db
    exec connector "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
