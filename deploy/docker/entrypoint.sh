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

wait_for_infra() {
  max_wait="${CONNECTOR_STARTUP_MAX_WAIT_SECONDS:-180}"
  sleep_seconds="${CONNECTOR_STARTUP_SLEEP_SECONDS:-5}"
  deadline=$(( $(date +%s) + max_wait ))

  while :; do
    if python - <<'PY'
import os
from sqlalchemy import create_engine, text
from redis import Redis

database_url = os.environ["DATABASE_URL"]
redis_url = os.environ["REDIS_URL"]

engine = create_engine(database_url, pool_pre_ping=True)
with engine.connect() as connection:
    connection.execute(text("select 1"))

client = Redis.from_url(redis_url)
client.ping()
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
  mkdir -p "$cache_dir" "$temp_dir" || fail "cannot create runtime directories: $cache_dir $temp_dir"
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

case "${1:-}" in
  check-config|--help|-h|help)
    exec connector "$@"
    ;;
  bootstrap)
    prepare_runtime_dirs
    run_startup_checks
    auto_init_db
    if truthy "${CONNECTOR_BOOTSTRAP_CHECK_LIVE:-true}"; then
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
  check-live|sync-once|controller|worker|reconciler)
    prepare_runtime_dirs
    run_startup_checks
    auto_init_db
    exec connector "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
