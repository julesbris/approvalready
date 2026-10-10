#!/usr/bin/env bash
# Browser (Playwright) end-to-end tests against a real stack, run as host processes: the API
# (uvicorn), a Celery worker and the production web build (next start). PostgreSQL and Redis
# must already be running (scripts/test-services.sh up, or CI service containers); the suite
# uses its own database (approvalready_e2e) and Redis database (14).
#
#   scripts/e2e.sh up      # recreate the database, migrate, build the web app, start everything
#   scripts/e2e.sh seed    # verified accounts, platform staff, a rule, an assessed project
#   scripts/e2e.sh test    # seed, then run Playwright (extra arguments go to playwright test)
#   scripts/e2e.sh down    # stop what `up` started
#   scripts/e2e.sh run     # up, test, down (what CI and `npm run test:e2e` do)
#
# Logs, process ids and the seed are kept in .e2e/ (E2E_STATE_DIR). E2E_SKIP_BUILD=1 reuses
# the existing apps/web/.next build. Never point this at a production database: the seed
# refuses unless APP_ENV is test or development, and `up` only drops a database named *_e2e.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="$ROOT/apps/api"
STATE="${E2E_STATE_DIR:-$ROOT/.e2e}"

PG_HOST="${E2E_PG_HOST:-127.0.0.1}"
PG_PORT="${E2E_PG_PORT:-5432}"
PG_USER="${E2E_PG_USER:-approvalready}"
PG_PASSWORD="${E2E_PG_PASSWORD:-approvalready}"
DB_NAME="${E2E_DB_NAME:-approvalready_e2e}"
# Login roles are cluster-wide: a separate one keeps clear of the API test suite's.
APP_ROLE="${E2E_APP_ROLE:-approvalready_e2e_app}"
API_PORT="${E2E_API_PORT:-8000}"
WEB_PORT="${E2E_WEB_PORT:-3000}"
API_URL="http://127.0.0.1:$API_PORT"
WEB_URL="http://127.0.0.1:$WEB_PORT"

# The API's settings (apps/api/app/core/config.py), as docker-compose.yml sets them for
# development, but on loopback addresses.
export APP_ENV=test
export LOG_LEVEL="${LOG_LEVEL:-INFO}"
export DATABASE_URL="postgresql+psycopg://$APP_ROLE:$APP_ROLE@$PG_HOST:$PG_PORT/$DB_NAME"
export REDIS_URL="${E2E_REDIS_URL:-redis://127.0.0.1:6379/14}"
export CORS_ORIGINS="$WEB_URL"
export ALLOWED_HOSTS="localhost,127.0.0.1"
export WEB_BASE_URL="$WEB_URL"
export COOKIE_SECURE=false
export EMAIL_PROVIDER=console
export STORAGE_LOCAL_ROOT="$STATE/uploads"
export MALWARE_SCANNER=eicar
export AI_PROVIDER=mock
export PAYMENTS_PROVIDER=none
export PROPERTY_FACTS_PROVIDER=none
export LOOKUPS_ENABLED=false
export JOBS_MODE=celery
# Every request comes from 127.0.0.1: lift the per-IP limit on sign-up and sign-in.
export AUTH_REQUESTS_PER_IP_PER_MINUTE=1000
OWNER_URL="postgresql+psycopg://$PG_USER:$PG_PASSWORD@$PG_HOST:$PG_PORT/$DB_NAME"

api_py() {
  (cd "$API_DIR" && MIGRATION_DATABASE_URL="$OWNER_URL" uv run --frozen --no-sync "$@")
}

# Start a long-running process in its own process group, logging to $STATE/<name>.log.
start() {
  local name="$1" dir="$2"
  shift 2
  echo "e2e: starting $name"
  # setsid (Linux) gives it its own process group, so `stop` also ends its children.
  local group=()
  if command -v setsid >/dev/null; then group=(setsid); fi
  (cd "$dir" && exec ${group[@]+"${group[@]}"} "$@" >"$STATE/$name.log" 2>&1 </dev/null) &
  echo $! >"$STATE/$name.pid"
}

stop() {
  local name="$1" file="$STATE/$1.pid"
  [[ -f "$file" ]] || return 0
  local pid
  pid="$(cat "$file")"
  if kill -0 "$pid" 2>/dev/null; then
    echo "e2e: stopping $name"
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    for _ in $(seq 1 50); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.2
    done
    kill -KILL -- "-$pid" 2>/dev/null || true
  fi
  rm -f "$file"
}

wait_for() {
  local name="$1" url="$2"
  for _ in $(seq 1 120); do
    if curl -fs -o /dev/null "$url"; then
      echo "e2e: $name ready ($url)"
      return 0
    fi
    if ! kill -0 "$(cat "$STATE/$name.pid")" 2>/dev/null; then
      echo "e2e: $name exited; last log lines:" >&2
      tail -n 50 "$STATE/$name.log" >&2
      return 1
    fi
    sleep 1
  done
  echo "e2e: $name did not become ready at $url" >&2
  tail -n 50 "$STATE/$name.log" >&2
  return 1
}

wait_for_worker() {
  for _ in $(seq 1 60); do
    if grep -q "ready\." "$STATE/worker.log" 2>/dev/null; then
      echo "e2e: worker ready"
      return 0
    fi
    sleep 1
  done
  echo "e2e: the worker did not start" >&2
  tail -n 50 "$STATE/worker.log" >&2
  return 1
}

up() {
  down
  mkdir -p "$STATE/uploads"
  (cd "$API_DIR" && uv sync --frozen)
  # A fresh database each time, then what the `migrate` entrypoint does
  # (apps/api/docker/entrypoint.sh), as the owner.
  api_py python scripts/e2e_stack.py reset
  api_py alembic upgrade head
  api_py python -m app.cli provision-db-role
  api_py python -m app.cli questionnaires sync
  api_py python -m app.cli marketplace sync-categories
  api_py python -m app.cli billing sync-catalogue
  api_py python -m app.cli leads sync-consent
  api_py python -m app.cli documents sync-templates
  api_py python -m app.cli ai sync-prompts

  # The API and worker connect as the application role (no MIGRATION_DATABASE_URL).
  start api "$API_DIR" uv run --frozen --no-sync uvicorn app.main:app \
    --host 127.0.0.1 --port "$API_PORT" --no-server-header
  start worker "$API_DIR" uv run --frozen --no-sync celery -A app.worker worker \
    --loglevel=INFO --concurrency=2 --hostname="e2e@%h"

  if [[ "${E2E_SKIP_BUILD:-0}" != "1" || ! -d "$ROOT/apps/web/.next" ]]; then
    echo "e2e: building the web app"
    (cd "$ROOT" && npm run build:web)
  fi
  start web "$ROOT/apps/web" env API_INTERNAL_URL="$API_URL" \
    npx next start --hostname 127.0.0.1 --port "$WEB_PORT"

  wait_for api "$API_URL/health/ready"
  wait_for_worker
  wait_for web "$WEB_URL/api/health"
}

seed() {
  mkdir -p "$STATE"
  E2E_API_URL="$API_URL" api_py python scripts/e2e_stack.py seed --out "$STATE/seed.json"
}

run_tests() {
  seed
  (cd "$ROOT" && E2E_BASE_URL="$WEB_URL" E2E_SEED_FILE="$STATE/seed.json" \
    npm run test:e2e --workspace @approvalready/web -- "$@")
}

down() {
  stop web
  stop worker
  stop api
}

case "${1:-}" in
  up) up ;;
  seed) seed ;;
  test)
    shift
    run_tests "$@"
    ;;
  down) down ;;
  run)
    shift
    trap down EXIT
    up
    run_tests "$@"
    ;;
  *)
    echo "usage: $0 up|seed|test|down|run [playwright args]" >&2
    exit 2
    ;;
esac
