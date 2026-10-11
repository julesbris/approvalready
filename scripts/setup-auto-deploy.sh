#!/usr/bin/env bash
# One-time setup for automatic deploys (DEPLOY_KAMATERA.md §16). Run on the server as deploy:
#
#   bash /srv/approvalready/scripts/setup-auto-deploy.sh
#
# Makes a new SSH key for GitHub that can only run scripts/deploy.sh, lets it in, and prints
# the two values to paste into GitHub's repository secrets. The private key is printed once
# and not kept on the server. Running it again replaces the key (paste the new one).
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/srv/approvalready}"
HOST="${DEPLOY_HOST:-45.151.154.206}"
TAG="approvalready-github-deploy"
AUTH="$HOME/.ssh/authorized_keys"

problems=()
[[ "$(id -un)" == "deploy" ]] || problems+=("run this as the deploy user (you are $(id -un))")
[[ -x "$APP_DIR/scripts/deploy.sh" ]] || problems+=("$APP_DIR/scripts/deploy.sh is missing: run git pull in $APP_DIR first")
id -nG | grep -qw docker || problems+=("the deploy user isn't in the docker group")
[[ -f "$APP_DIR/.env" ]] || problems+=("$APP_DIR/.env is missing")
[[ -r /etc/ssh/ssh_host_ed25519_key.pub ]] || problems+=("this server has no ed25519 host key")
if ((${#problems[@]})); then
  printf 'Not set up:\n' >&2
  printf '  - %s\n' "${problems[@]}" >&2
  exit 1
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
ssh-keygen -q -t ed25519 -N "" -C "$TAG" -f "$tmp/key"

mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
touch "$AUTH" && chmod 600 "$AUTH"
# Replace an earlier key from this script, keep every other key.
grep -v " $TAG\$" "$AUTH" >"$tmp/auth" || true
echo "command=\"$APP_DIR/scripts/deploy.sh\",restrict $(cat "$tmp/key.pub")" >>"$tmp/auth"
cat "$tmp/auth" >"$AUTH"

host_key="$(cut -d' ' -f1,2 /etc/ssh/ssh_host_ed25519_key.pub)"

cat <<EOF

Done. GitHub's key is allowed in, and can only run the deploy.

Now open https://github.com/julesbris/approvalready/settings/secrets/actions
and add two secrets with "New repository secret".

1) Name:   DEPLOY_SSH_KEY
   Secret: everything between the two lines of dashes below, including the
           BEGIN and END lines.
------------------------------------------------------------------------
$(cat "$tmp/key")
------------------------------------------------------------------------

2) Name:   DEPLOY_KNOWN_HOSTS
   Secret: this one line:
------------------------------------------------------------------------
$HOST $host_key
------------------------------------------------------------------------

The private key above isn't saved on this server. If you lose it, run this script again.
EOF
