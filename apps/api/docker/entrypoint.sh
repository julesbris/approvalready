#!/bin/sh
# Container entrypoint. One image, several roles.
set -eu

case "${1:-api}" in
  api)
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 \
      --proxy-headers --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-127.0.0.1}" \
      --workers "${WEB_CONCURRENCY:-2}" --no-server-header
    ;;
  api-dev)
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
    ;;
  worker)
    exec celery -A app.worker worker --loglevel="${LOG_LEVEL:-INFO}" --concurrency="${WORKER_CONCURRENCY:-2}"
    ;;
  scheduler)
    exec celery -A app.worker beat --loglevel="${LOG_LEVEL:-INFO}" --schedule=/tmp/celerybeat-schedule
    ;;
  migrate)
    exec alembic upgrade head
    ;;
  *)
    exec "$@"
    ;;
esac
