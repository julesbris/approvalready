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
    # As the owner (MIGRATION_DATABASE_URL): schema, then the application's login role,
    # then publish changed questionnaire definitions, marketplace categories, report
    # templates and AI prompts.
    alembic upgrade head
    python -m app.cli provision-db-role
    python -m app.cli questionnaires sync
    python -m app.cli marketplace sync-categories
    python -m app.cli documents sync-templates
    exec python -m app.cli ai sync-prompts
    ;;
  *)
    exec "$@"
    ;;
esac
