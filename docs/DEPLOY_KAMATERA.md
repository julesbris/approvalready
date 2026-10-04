# Deploying ApprovalReady on Kamatera

Single Ubuntu LTS cloud server running `docker-compose.prod.yml`. This is the Milestone 1
runbook; Milestone 17 adds monitoring, WAL archiving and security testing.

```
Internet → Cloudflare (DNS, proxy, WAF) → Caddy :443 → web (Next.js) / api (FastAPI)
                                                         ↘ worker, scheduler
                                    internal-only network: PostgreSQL 18, Redis
```

## 1. Server

* Kamatera: Ubuntu Server 24.04 LTS (or the newest LTS offered), Sydney data centre
  (`AU-SY`) for Australian data residency. Start at 4 vCPU / 8 GB RAM / 80 GB SSD.
* Enable Kamatera's firewall (in the console) with the same rules as UFW below, so traffic
  is filtered before it reaches the VM.

## 2. Deployment user and SSH

```bash
# as root, once
adduser --disabled-password --gecos "" deploy
usermod -aG sudo deploy
mkdir -p /home/deploy/.ssh && chmod 700 /home/deploy/.ssh
# paste your ed25519 public key:
nano /home/deploy/.ssh/authorized_keys && chmod 600 /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh
```

Harden `/etc/ssh/sshd_config.d/10-hardening.conf`:

```
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
AllowUsers deploy
MaxAuthTries 3
```

`systemctl reload ssh`, confirm a new session works **before** closing the root one.
Install `fail2ban` and `unattended-upgrades` (`dpkg-reconfigure -plow unattended-upgrades`).

## 3. Firewall

```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow from <your-office-ip>/32 to any port 22 proto tcp   # or 22/tcp if IP varies
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp     # HTTP/3
ufw enable
```

**Docker bypasses UFW for published ports.** That is why only the `proxy` service publishes
ports in `docker-compose.prod.yml`; PostgreSQL and Redis publish nothing and sit on an
`internal: true` network. `tests/infrastructure/test_compose_security.py` enforces this in
CI. Never add `ports:` to `db` or `redis`; use `docker compose exec db psql` or an SSH
tunnel to a temporary loopback-bound port for maintenance.

## 4. Docker

```bash
sudo apt-get update && sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update && sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker deploy
```

Optionally set `/etc/docker/daemon.json` → `{"log-driver":"json-file","log-opts":{"max-size":"20m","max-file":"5"},"live-restore":true}`.

## 5. DNS and TLS

In Cloudflare, create proxied (orange cloud) records pointing at the server IP:

| Name | Type |
|---|---|
| `approvalready.com.au` | A |
| `www`, `app`, `partners`, `review`, `api` | A (or CNAME to apex) |

TLS options (pick one):

1. **Let's Encrypt via Caddy (default).** Set Cloudflare SSL/TLS mode to **Full (strict)**.
   Caddy obtains certificates automatically. HTTP-01 works through Cloudflare's proxy.
2. **Cloudflare Origin Certificate.** Mount the cert/key into the proxy and add
   `tls /certs/origin.pem /certs/origin.key` to each site block. Then restrict 80/443 in the
   firewall to [Cloudflare IP ranges](https://www.cloudflare.com/ips/) so the origin cannot
   be reached directly.

When proxied by Cloudflare, add Cloudflare's ranges to `trusted_proxies` in the Caddyfile so
client IPs (used for rate limiting and audit logs from Milestone 2) are correct.

Marketing domains (e.g. `planningready.com.au`) get their own DNS record and a redirect
block in the Caddyfile once owned. Availability is not assumed.

## 6. Application files and environment

```bash
sudo mkdir -p /srv/approvalready && sudo chown deploy:deploy /srv/approvalready
cd /srv/approvalready
git clone <repo-url> .
cp .env.example .env && chmod 600 .env
```

Fill `.env`. Generate secrets with `openssl rand -hex 32` (hex keeps them URL-safe for the
database DSN). Required: `PRIMARY_DOMAIN`, `ACME_EMAIL`, `CORS_ORIGINS` (https only),
`ALLOWED_HOSTS` (include `api.<domain>`), `SECRET_KEY` (≥ 32 chars), `POSTGRES_PASSWORD`,
`REDIS_PASSWORD`. The API refuses to start in production with unsafe values.
Validate: `make prod-config`.

## 7. First deployment

```bash
docker compose -f docker-compose.prod.yml --env-file .env build
docker compose -f docker-compose.prod.yml --env-file .env up -d --wait
```

`migrate` runs `alembic upgrade head` once and exits; `api` and `worker` start only after it
succeeds.

## 8. Persistent volumes

| Volume | Contents | Backed up |
|---|---|---|
| `pgdata` | PostgreSQL cluster (PG18 layout under `/var/lib/postgresql`) | Yes (dumps + later WAL) |
| `redisdata` | Redis AOF (queues, rate counters) | No (rebuildable) |
| `caddy_data` | TLS certificates and ACME account | Optional |
| `./backups` (bind) | Local dump staging | Shipped off-host |

Uploaded documents go to S3-compatible object storage from Milestone 6, never to these volumes.

## 9. Migrations (Alembic)

* Every deploy runs `migrate` before the new `api` starts.
* Migrations must be **backwards compatible with the previous release** (expand → deploy →
  contract): add nullable columns / new tables first; drop or tighten only in a later release.
* Manual: `docker compose -f docker-compose.prod.yml run --rm migrate`.
* Rollback of code is preferred to `alembic downgrade` in production.

## 10. Backups

Nightly logical backup (cron as `deploy`, 02:30 AEST):

```bash
#!/usr/bin/env bash
set -euo pipefail
cd /srv/approvalready
ts=$(date -u +%Y%m%dT%H%M%SZ)
docker compose -f docker-compose.prod.yml exec -T db \
  sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "backups/db-$ts.dump"
# ship off-host (S3-compatible, Australian region), then prune local copies
aws s3 cp "backups/db-$ts.dump" "s3://<backup-bucket>/postgres/" --endpoint-url "<endpoint>"
find backups -name 'db-*.dump' -mtime +7 -delete
```

Encrypt the bucket, enable object lock/versioning, keep 35 daily + 12 monthly. Milestone 17
adds continuous WAL archiving (pgBackRest or WAL-G) for point-in-time recovery.

## 11. Restore procedure (test quarterly)

```bash
docker compose -f docker-compose.prod.yml stop api worker scheduler
docker compose -f docker-compose.prod.yml exec -T db \
  sh -c 'dropdb -U "$POSTGRES_USER" --if-exists "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
docker compose -f docker-compose.prod.yml exec -T db \
  sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner' < backups/db-<ts>.dump
docker compose -f docker-compose.prod.yml run --rm migrate
docker compose -f docker-compose.prod.yml up -d --wait
curl -fsS https://api.<domain>/health/ready
```

Record restore duration; that is your real recovery time.

## 12. Health checks

| Endpoint | Meaning | Used by |
|---|---|---|
| `GET /health/live` (api) | Process serving | Docker HEALTHCHECK, Caddy upstream check |
| `GET /health/ready` (api) | PostgreSQL + Redis reachable; 503 otherwise | External uptime monitor |
| `GET /version` (api) | Version, git SHA, environment | Deploy verification |
| `GET /api/health` (web) | Web serving, plus API status | Docker HEALTHCHECK, Caddy |
| `celery inspect ping` | Worker responsive | Docker HEALTHCHECK |

Point an external monitor (e.g. UptimeRobot, Better Stack) at `https://api.<domain>/health/ready`
and `https://<domain>/api/health`.

## 13. Rolling deployment

Single host, minimal downtime:

```bash
cd /srv/approvalready
git fetch && git checkout <release-tag>
export GIT_SHA=$(git rev-parse --short HEAD) IMAGE_TAG=$(git rev-parse --short HEAD)
docker compose -f docker-compose.prod.yml --env-file .env build
docker compose -f docker-compose.prod.yml --env-file .env run --rm migrate
docker compose -f docker-compose.prod.yml --env-file .env up -d --no-deps --wait api
docker compose -f docker-compose.prod.yml --env-file .env up -d --no-deps --wait web
docker compose -f docker-compose.prod.yml --env-file .env up -d --no-deps worker scheduler
curl -fsS https://api.<domain>/version
```

Containers are replaced one service at a time; Caddy retries upstreams during the brief
swap. Roll back by checking out the previous tag (images are tagged by SHA) and repeating
the `up` steps. For true zero-downtime later: run two `api`/`web` replicas
(`--scale api=2`) so Caddy load-balances across them, or build images in CI and pull from
a registry.

## 14. Scaling path (no code changes)

| Need | Change |
|---|---|
| Separate database server | Point `DATABASE_URL` at it (private network, TLS), remove `db` service |
| Separate worker server | Run `worker` on a second host against the same Redis/DB over a private network |
| Object storage / CDN | `STORAGE_BACKEND=s3` (Milestone 6); Cloudflare caches `/_next/static` |
| More API/web capacity | Multiple replicas or hosts behind Caddy / a load balancer; sessions live in Postgres so any node serves any user |
