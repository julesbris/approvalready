#!/bin/sh
# ApprovalReady backups (Milestone 17). Runs in the `backup` service of docker-compose.prod.yml
# (the postgres image, so pg_dump and pg_restore match the server), on the internal data
# network only. It writes to the `backups` volume; the worker copies new files off the server
# when BACKUP_S3_BUCKET is set. Every backup and restore check is recorded in `backup_run`,
# which /admin/ops shows and the watchdog alerts on.
#
#   backup.sh loop                      run backups on schedule (the service's command)
#   backup.sh now                       back up now
#   backup.sh restore-check [db-X.dump] restore a dump into a scratch database and check it
#   backup.sh list                      list the backups on the server
#   backup.sh restore db-X.dump [uploads-X.tgz] --yes
#                                       REPLACE the database (and files) with a backup
#
# Settings (environment): BACKUP_TIMES (Brisbane times, default "02:30"; e.g. "02:30,14:30"),
# BACKUP_KEEP_DAYS (copies kept on the server, default 14), BACKUP_RESTORE_CHECK_DAY (1-7,
# Monday-Sunday, default 7). PGHOST, PGUSER, PGPASSWORD and PGDATABASE name the database.
set -eu

DIR="${BACKUP_DIR:-/backups}"
UPLOADS="${BACKUP_UPLOADS_DIR:-/uploads}"
TIMES="${BACKUP_TIMES:-02:30}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
CHECK_DAY="${BACKUP_RESTORE_CHECK_DAY:-7}"
APP_UID="${BACKUP_UID:-10001}"
APP_GROUP_ROLE="approvalready_rw"
SCRATCH_DB="${PGDATABASE:?PGDATABASE is required}_restore_check"
export PGCONNECT_TIMEOUT=10

log() { printf '%s backup: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
die() { log "ERROR: $*"; exit 1; }

# --- Recording ---------------------------------------------------------------------------

# record KIND STATUS STARTED DB_FILE DB_BYTES DB_SHA UPLOADS_FILE UPLOADS_BYTES UPLOADS_SHA DETAIL
# Values travel as psql variables (quoted by psql), never pasted into SQL.
record() {
  offsite=""
  if [ "$1" = BACKUP ] && [ "$2" = OK ]; then offsite=PENDING; fi
  psql -X -q -v ON_ERROR_STOP=1 \
    -v kind="$1" -v status="$2" -v started="$3" \
    -v db_file="$4" -v db_bytes="$5" -v db_sha="$6" \
    -v up_file="$7" -v up_bytes="$8" -v up_sha="$9" -v detail="${10}" -v offsite="$offsite" \
    >/dev/null <<'SQL' || log "could not record the run in backup_run"
INSERT INTO backup_run (kind, status, started_at, database_file, database_bytes,
  database_sha256, uploads_file, uploads_bytes, uploads_sha256, detail, offsite_status)
VALUES (:'kind', :'status', :'started'::timestamptz, nullif(:'db_file', ''),
  nullif(:'db_bytes', '')::bigint, nullif(:'db_sha', ''), nullif(:'up_file', ''),
  nullif(:'up_bytes', '')::bigint, nullif(:'up_sha', ''), nullif(:'detail', ''),
  nullif(:'offsite', ''));
SQL
}

size_of() { stat -c %s "$1"; }
sha_of() { sha256sum "$1" | cut -d' ' -f1; }

# --- Backup ------------------------------------------------------------------------------

backup() {
  started=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  db_file="db-$stamp.dump"
  up_file="uploads-$stamp.tgz"
  err="${DIR:?}/.backup-error"
  umask 077
  log "backing up database $PGDATABASE to $db_file"
  if ! pg_dump -Fc -f "${DIR:?}/$db_file.partial" 2>"$err"; then
    detail="pg_dump failed: $(tail -c 400 "$err")"
    rm -f "${DIR:?}/$db_file.partial"
    record BACKUP FAILED "$started" "" "" "" "" "" "" "$detail"
    die "$detail"
  fi
  mv "${DIR:?}/$db_file.partial" "${DIR:?}/$db_file"
  if [ -d "$UPLOADS" ]; then
    log "archiving uploaded files to $up_file"
    if ! tar -czf "${DIR:?}/$up_file.partial" -C "$UPLOADS" . 2>"$err"; then
      detail="archiving uploads failed: $(tail -c 400 "$err")"
      rm -f "${DIR:?}/$up_file.partial"
      record BACKUP FAILED "$started" "$db_file" "" "" "" "" "" "$detail"
      die "$detail"
    fi
    mv "${DIR:?}/$up_file.partial" "${DIR:?}/$up_file"
    up_bytes=$(size_of "$DIR/$up_file")
    up_sha=$(sha_of "$DIR/$up_file")
  else
    up_file="" up_bytes="" up_sha=""
  fi
  rm -f "$err"
  db_bytes=$(size_of "$DIR/$db_file")
  record BACKUP OK "$started" "$db_file" "$db_bytes" "$(sha_of "$DIR/$db_file")" \
    "$up_file" "$up_bytes" "$up_sha" ""
  # Old copies go only after a good backup, so the newest one always stays.
  find "${DIR:?}" -maxdepth 1 \( -name 'db-*.dump' -o -name 'uploads-*.tgz' \) \
    -mtime +"$KEEP_DAYS" -exec rm -f {} \;
  log "backup done: $db_file ($db_bytes bytes)${up_file:+, $up_file ($up_bytes bytes)}"
}

latest() { ls -1 "$DIR"/$1 2>/dev/null | sort | tail -n 1; }

# --- Restore check -----------------------------------------------------------------------

scratch_sql() { psql -X -q -t -A -v ON_ERROR_STOP=1 -d "$SCRATCH_DB" -c "$1"; }

check_failed() {
  dropdb --if-exists "$SCRATCH_DB" >/dev/null 2>&1 || true
  record RESTORE_CHECK FAILED "$started" "$name" "" "" "" "" "" "$1"
  die "$1"
}

restore_check() {
  started=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  dump="${1:-$(latest 'db-*.dump')}"
  [ -n "$dump" ] || die "no backup to check"
  case "$dump" in */*) ;; *) dump="$DIR/$dump" ;; esac
  name=$(basename "$dump")
  err="${DIR:?}/.restore-error"
  log "restore check of $name into $SCRATCH_DB"
  t0=$(date +%s)
  dropdb --if-exists "$SCRATCH_DB" 2>"$err" \
    || check_failed "dropping the scratch database failed: $(tail -c 300 "$err")"
  createdb "$SCRATCH_DB" 2>"$err" \
    || check_failed "creating the scratch database failed: $(tail -c 300 "$err")"
  # No privileges: nothing but the owner can read the scratch copy.
  pg_restore --no-owner --no-privileges --exit-on-error -d "$SCRATCH_DB" "$dump" 2>"$err" \
    || check_failed "pg_restore failed: $(tail -c 400 "$err")"
  expected=$(pg_restore -l "$dump" | grep -c ' TABLE DATA public ' || true)
  tables=$(scratch_sql "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
  version=$(scratch_sql "SELECT version_num FROM alembic_version" 2>/dev/null || true)
  users=$(scratch_sql "SELECT count(*) FROM app_user" 2>/dev/null || echo "?")
  orgs=$(scratch_sql "SELECT count(*) FROM organisation" 2>/dev/null || echo "?")
  projects=$(scratch_sql "SELECT count(*) FROM project" 2>/dev/null || echo "?")
  [ -n "$version" ] || check_failed "the restored database has no schema version"
  [ "$tables" -ge "$expected" ] || check_failed "restored $tables tables, the backup lists $expected"
  files="no files archive"
  up="$DIR/$(echo "$name" | sed 's/^db-\(.*\)\.dump$/uploads-\1.tgz/')"
  if [ -f "$up" ]; then
    tar -tzf "$up" >"$err.list" 2>"$err" \
      || check_failed "the files archive is unreadable: $(tail -c 300 "$err")"
    files="$(grep -vc '/$' "$err.list" || true) files readable"
    rm -f "$err.list"
  fi
  dropdb "$SCRATCH_DB"
  rm -f "$err"
  seconds=$(( $(date +%s) - t0 ))
  detail="$tables tables, schema $version, $users users, $orgs organisations, $projects projects; $files; took ${seconds}s"
  record RESTORE_CHECK OK "$started" "$name" "$(size_of "$dump")" "" "" "" "" "$detail"
  log "restore check passed: $detail"
}

# --- Full restore (disaster recovery) ----------------------------------------------------

restore() {
  dump="" up="" yes=""
  for arg in "$@"; do
    case "$arg" in
      --yes) yes=1 ;;
      *.dump) dump="$arg" ;;
      *.tgz) up="$arg" ;;
      *) die "unexpected argument: $arg" ;;
    esac
  done
  [ -n "$dump" ] || die "usage: backup.sh restore db-X.dump [uploads-X.tgz] --yes"
  case "$dump" in */*) ;; *) dump="$DIR/$dump" ;; esac
  [ -f "$dump" ] || die "no such backup: $dump"
  if [ -n "$up" ]; then
    case "$up" in */*) ;; *) up="$DIR/$up" ;; esac
    [ -f "$up" ] || die "no such files archive: $up"
    target="${BACKUP_RESTORE_UPLOADS_DIR:-/restore-uploads}"
    [ -d "$target" ] && [ -w "$target" ] \
      || die "mount the uploads volume writable at $target to restore files"
  fi
  if [ -z "$yes" ]; then
    die "this REPLACES database $PGDATABASE with $(basename "$dump"); add --yes to go ahead"
  fi
  log "replacing database $PGDATABASE with $(basename "$dump")"
  psql -X -q -v ON_ERROR_STOP=1 -d postgres -v db="$PGDATABASE" >/dev/null <<'SQL'
SELECT pg_terminate_backend(pid) FROM pg_stat_activity
WHERE datname = :'db' AND pid <> pg_backend_pid();
SQL
  dropdb --if-exists "$PGDATABASE"
  createdb "$PGDATABASE"
  # On a new server the privilege group doesn't exist yet; the dump grants to it.
  psql -X -q -v ON_ERROR_STOP=1 -d postgres >/dev/null <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$APP_GROUP_ROLE') THEN
    CREATE ROLE $APP_GROUP_ROLE NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
  END IF;
END \$\$;
SQL
  pg_restore --no-owner --exit-on-error -d "$PGDATABASE" "$dump"
  log "database restored"
  if [ -n "$up" ]; then
    find "${target:?}" -mindepth 1 -delete
    tar -xzf "$up" -C "$target"
    log "files restored from $(basename "$up")"
  fi
  log "now run the migrate service and start the app again (see docs/DEPLOY_KAMATERA.md)"
}

# --- Schedule ----------------------------------------------------------------------------

minutes() { echo "$1" | awk -F: '{ print $1 * 60 + $2 }'; }

# The most recent scheduled time that has passed, as "YYYY-MM-DD HH:MM" (Brisbane).
due_slot() {
  now=$(minutes "$(date +%H:%M)")
  slot=""
  for t in $(echo "$TIMES" | tr ',' '\n' | sort); do
    if [ "$(minutes "$t")" -le "$now" ]; then slot="$(date +%Y-%m-%d) $t"; fi
  done
  if [ -z "$slot" ]; then
    last=$(echo "$TIMES" | tr ',' '\n' | sort | tail -n 1)
    slot="$(date -d "@$(( $(date +%s) - 86400 ))" +%Y-%m-%d) $last"
  fi
  echo "$slot"
}

loop() {
  for t in $(echo "$TIMES" | tr ',' ' '); do
    echo "$t" | grep -Eq '^([01][0-9]|2[0-3]):[0-5][0-9]$' || die "BACKUP_TIMES: bad time $t"
  done
  log "scheduled at $TIMES ($(date +%Z)), keeping $KEEP_DAYS days; restore check on day $CHECK_DAY"
  while true; do
    slot=$(due_slot)
    if [ "$slot" != "$(cat "$DIR/.last-slot" 2>/dev/null || true)" ]; then
      # The slot is marked first: a failing backup is alerted on, not retried in a loop.
      echo "$slot" >"$DIR/.last-slot"
      if (backup); then
        if [ "$(date +%u)" = "$CHECK_DAY" ] || [ ! -f "$DIR/.restore-checked" ]; then
          if (restore_check); then
            date -u +%Y-%m-%dT%H:%M:%SZ >"$DIR/.restore-checked"
          fi
        fi
      fi
    fi
    sleep 60
  done
}

if [ "$(id -u)" = 0 ]; then
  # Everything runs as the app user: its files are what the worker (same uid) copies off the
  # server, and uploaded files are private to it. `docker compose exec` arrives as root.
  mkdir -p "$DIR"
  chown "$APP_UID:$APP_UID" "$DIR"
  chmod 700 "$DIR"
  exec gosu "$APP_UID:$APP_UID" sh "$0" "$@"
fi

case "${1:-loop}" in
  loop) loop ;;
  now) backup ;;
  restore-check) restore_check "${2:-}" ;;
  restore) shift; restore "$@" ;;
  list) ls -lh "$DIR" | grep -E 'db-|uploads-' || log "no backups yet" ;;
  *) die "unknown command: $1 (loop, now, restore-check, list, restore)" ;;
esac
