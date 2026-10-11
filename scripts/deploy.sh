#!/usr/bin/env bash
# Deploy the newest main to this server: pull, rebuild and restart (migrations run in the
# migrate service), then load every rule content pack. See DEPLOY_KAMATERA.md §16.
#
#   scripts/deploy.sh            # on the server, as deploy, from anywhere
#
# The GitHub "Deploy" workflow runs this over SSH with a key that can run nothing else
# (scripts/setup-auto-deploy.sh). Only one deploy runs at a time; a second one waits.
# It never edits .env: a missing required setting stops the deploy before anything restarts.
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/srv/approvalready}"
BRANCH="${DEPLOY_BRANCH:-main}"
PACK_EMAIL="${DEPLOY_PACK_EMAIL:-team@approvalready.au}"
LOCK_FILE="${DEPLOY_LOCK_FILE:-/tmp/approvalready-deploy.lock}"
COMPOSE=(docker compose -f docker-compose.prod.yml --env-file .env)

say() { printf '\n==> %s\n' "$*"; }
fail() {
  printf '\nDEPLOY FAILED: %s\n' "$*" >&2
  exit 1
}

cd "$APP_DIR" || fail "$APP_DIR does not exist"

# Stage 1: take the lock, get the new code, then run the new copy of this script, so a change
# to the deploy steps takes effect in the same deploy. The lock's file descriptor survives exec.
if [[ "${1:-}" != "--pulled" ]]; then
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    echo "Another deploy is running; waiting for it to finish..."
    flock -w 3600 9 || fail "another deploy has held the lock for an hour"
  fi
  say "Getting the newest code ($BRANCH)"
  if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    git status --short --untracked-files=no
    fail "files in $APP_DIR were changed by hand (listed above). Undo them with
  git checkout -- <file>
then deploy again."
  fi
  current="$(git rev-parse --abbrev-ref HEAD)"
  [[ "$current" == "$BRANCH" ]] || fail "the server is on branch $current, not $BRANCH"
  git fetch --quiet origin "$BRANCH"
  git merge --ff-only --quiet "origin/$BRANCH" || fail "can't fast-forward to origin/$BRANCH"
  exec "$APP_DIR/scripts/deploy.sh" --pulled
fi

sha="$(git rev-parse --short=12 HEAD)"
echo "Deploying $(git log -1 --format='%h %s')"

say "Checking .env"
[[ -f .env ]] || fail ".env is missing"
# Compose refuses to run while a required setting (marked :? in docker-compose.prod.yml) is
# missing, and its message names the setting.
if ! config_errors="$("${COMPOSE[@]}" config -q 2>&1)"; then
  echo "$config_errors" >&2
  fail "a required setting is missing from .env (named above). Add it, then deploy again."
fi
warnings=()
placeholders="$(grep -E '^[A-Z0-9_]+=.*replace-with' .env | cut -d= -f1 | paste -sd, || true)"
[[ -z "$placeholders" ]] ||
  warnings+=("these .env settings still have the example value; set real secrets: $placeholders")
grep -qE '^OPS_ALERT_EMAILS=.+' .env ||
  warnings+=("OPS_ALERT_EMAILS isn't set in .env, so problems and privacy requests aren't emailed to you")
echo "OK"

say "Rebuilding and restarting (database updates run first)"
export GIT_SHA="$sha"
if ! "${COMPOSE[@]}" up -d --build --wait; then
  "${COMPOSE[@]}" ps -a || true
  echo "--- migrate log ---"
  "${COMPOSE[@]}" logs --tail 60 migrate || true
  echo "--- api log ---"
  "${COMPOSE[@]}" logs --tail 60 api || true
  fail "the new version didn't start (logs above). The services that did start are running it."
fi
"${COMPOSE[@]}" ps
echo "Database version: $("${COMPOSE[@]}" exec -T api alembic current 2>/dev/null | tail -n 1)"

say "Loading rule content packs as $PACK_EMAIL"
failed_packs=()
shopt -s nullglob
packs=(apps/api/app/modules/rules/packs/*.json)
((${#packs[@]})) || warnings+=("no rule content packs found to load")
for file in "${packs[@]}"; do
  pack="$(basename "$file" .json)"
  echo "--- $pack"
  # Loading again changes nothing that is already there; only what's new or changed is listed.
  if output="$("${COMPOSE[@]}" exec -T api python -m app.cli rules load-pack "$pack" \
    --email "$PACK_EMAIL" --publish --update 2>&1)"; then
    grep -v '^already there' <<<"$output" || true
    echo "($(grep -c '^already there' <<<"$output" || true) item(s) already there)"
  else
    echo "$output"
    failed_packs+=("$pack")
  fi
done

say "Tidying up old images"
docker image prune -f >/dev/null || true
echo "OK"

for w in "${warnings[@]+"${warnings[@]}"}"; do echo "WARNING: $w"; done
echo "DEPLOYED_SHA=$sha"
if ((${#failed_packs[@]})); then
  fail "the site is updated, but these rule packs didn't load: ${failed_packs[*]} (see above)"
fi
say "Done: $sha is live"
