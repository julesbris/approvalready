#!/usr/bin/env bash
# Start throwaway PostgreSQL 18 and Redis containers for the API test suite.
#   scripts/test-services.sh up     # start (idempotent)
#   scripts/test-services.sh down   # remove
set -euo pipefail

PG_PORT="${TEST_PG_PORT:-5432}"
REDIS_PORT="${TEST_REDIS_PORT:-6379}"

case "${1:-up}" in
  up)
    docker inspect ar-test-pg >/dev/null 2>&1 || docker run -d --name ar-test-pg \
      -e POSTGRES_USER=approvalready -e POSTGRES_PASSWORD=approvalready \
      -e POSTGRES_DB=approvalready_test -p "127.0.0.1:${PG_PORT}:5432" postgres:18-alpine >/dev/null
    docker inspect ar-test-redis >/dev/null 2>&1 || docker run -d --name ar-test-redis \
      -p "127.0.0.1:${REDIS_PORT}:6379" redis:8-alpine >/dev/null
    for _ in $(seq 1 30); do
      if docker exec ar-test-pg pg_isready -U approvalready -d approvalready_test >/dev/null 2>&1 \
        && docker exec ar-test-redis redis-cli ping >/dev/null 2>&1; then
        echo "test services ready (postgres :${PG_PORT}, redis :${REDIS_PORT})"
        exit 0
      fi
      sleep 1
    done
    echo "test services did not become ready" >&2
    exit 1
    ;;
  down)
    docker rm -f ar-test-pg ar-test-redis >/dev/null 2>&1 || true
    ;;
  *)
    echo "usage: $0 up|down" >&2
    exit 2
    ;;
esac
