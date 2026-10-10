# Deploying ApprovalReady on Kamatera

Single Ubuntu LTS cloud server running `docker-compose.prod.yml`. Production runs at
`approvalready.au`. Milestone 17 added backups with restore checks (§10, §11), monitoring and
alerts (§12) and security testing in CI (§15).

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
`APP_DB_PASSWORD` (different from `POSTGRES_PASSWORD`; `APP_DB_USER` defaults to
`approvalready_app`),
`REDIS_PASSWORD`, `EMAIL_FROM`, `SMTP_HOST` (plus `SMTP_USERNAME`/`SMTP_PASSWORD` for the
relay; STARTTLS on 587 with certificate verification by default). The API refuses to start in
production with unsafe values (including non-Secure cookies or a non-https `WEB_BASE_URL`).
`SECRET_KEY` also signs CSRF tokens: changing it forces users to reload open pages.
Validate: `make prod-config`.

## 7. First deployment

```bash
docker compose -f docker-compose.prod.yml --env-file .env build
docker compose -f docker-compose.prod.yml --env-file .env up -d --wait
```

`migrate` runs once and exits; `api` and `worker` start only after it succeeds. It is the only
service given the database owner's credentials, and it:

1. runs `alembic upgrade head`;
2. runs `python -m app.cli provision-db-role`, which creates or updates the application's login
   role (`APP_DB_USER`/`APP_DB_PASSWORD`) without superuser, BYPASSRLS or ownership, so
   row-level security applies to everything the API and worker do;
3. runs `python -m app.cli questionnaires sync`, publishing any changed questionnaire
   definitions as new versions (unchanged ones are left alone);
4. runs `python -m app.cli marketplace sync-categories`, applying the reviewed marketplace
   category list;
5. runs `python -m app.cli documents sync-templates`, publishing changed report templates.

`/health/ready` reports `database_role` as failing in production if the API's role is ever a
superuser, can bypass RLS or owns tables. To rotate `APP_DB_PASSWORD`, change it in `.env` and
re-run `migrate` before restarting `api` and `worker`.

Create the first administrator: register and confirm an account through the web app, then

```bash
docker compose -f docker-compose.prod.yml --env-file .env exec api \
  python -m app.cli grant-platform-role --email you@example.com --role SUPERADMIN
```

This creates the `PLATFORM_ADMIN` organisation on first use. There is no HTTP endpoint for
this step by design. Check the audit log's hash chain at any time with
`... exec api python -m app.cli verify-audit`.

### Loading rule content packs (Milestone 5)

Rules are not loaded by deploys. A content pack (reviewed JSON in
`apps/api/app/modules/rules/packs/`) is loaded on purpose by a platform staff member, whose
account is named in the audit log for everything it creates:

```bash
docker compose -f docker-compose.prod.yml --env-file .env exec api \
  python -m app.cli rules load-pack planning_qld_cairns --email you@example.com
```

This creates the pack's sources (all **unverified**) and its rules as **drafts**. Nothing
reaches customers until someone publishes the rules at `/admin/rules`. Adding `--publish`
publishes every rule that passes the publish gate in the same step (needs an admin, because
publishing needs `rule.publish`); findings stay "likely" at best until the sources are
captured and verified at `/admin/sources`. Running the command again changes nothing that
already exists.

Available packs: `planning_qld_cairns` (Milestone 5), `business_qld_cairns` (Milestone 8,
BusinessReady rules for Queensland and Cairns) and `vessel_au_qld` (Milestone 9, VesselReady
rules for domestic commercial vessels from AMSA, and Queensland recreational registration
and licences) and `grants_au_qld` (Milestone 10, GrantReady: three grant programs with their
eligibility rules and first rounds; keep rounds current at `/admin/grants`) and `property_qld`
(Milestone 11, SellReady seller disclosure and RentReady tenancy rules for Queensland).

From Milestone 11 the `scheduler` service sends reminders and notifications (every 5 minutes)
and daily alerts (07:30 Brisbane). It must be running for reminders to arrive; check it with
`docker compose -f docker-compose.prod.yml --env-file .env logs --tail 50 scheduler`.

### AI drafting (Milestone 12)

Off by default: customers see no AI buttons. To switch it on, add an Anthropic API key to
`.env` and redeploy:

```bash
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

Customers then get "Explain these findings in plain language" on assessments and "Draft
application notes" on grant matches. Every call is logged; staff with `platform.audit.read`
(admins) see calls, tokens and cost at `/admin/ai`. Prompts are reviewed files published by
the migrate step, like report templates. Set `AI_PROVIDER=none` (or remove the key) to switch
it off again; existing drafts stay visible to their owners only while it is on.

### Payments (Milestone 13)

Off by default: nothing is for sale and no plan limits apply. To switch Stripe on:

1. In the Stripe dashboard (start in test mode), copy the secret key from Developers → API
   keys.
2. Developers → Webhooks → Add endpoint: `https://api.<PRIMARY_DOMAIN>/v1/billing/stripe/webhook`,
   with the events listed at `/admin/billing` (checkout sessions, customer subscriptions,
   invoices and `charge.refunded`). Copy its signing secret (`whsec_...`).
3. Settings → Billing → Customer portal: turn it on (customers change cards, download
   invoices and cancel plans there).
4. Add to `.env` and redeploy:

```bash
PAYMENTS_PROVIDER=stripe
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

5. Set prices at `/admin/billing` (platform ADMIN). A product without a price is not on sale.
   Professional reviews then ask for payment before staff can assign them, and the
   RentReady plans limit how many rentals a free account manages.

Webhooks are verified (signature and a 5-minute timestamp window), stored once by event id
and applied by the worker; the browser never decides what was paid. Refunds are made in the
Stripe dashboard and come back by webhook. To go live, swap in the live secret key and a live
webhook endpoint's secret.

### Partner accounts (Milestone 14)

The partner portal is served at `https://partners.<PRIMARY_DOMAIN>` (the `partners` DNS record
from §5; Caddy already serves that host). Businesses apply there; staff with `partner.verify`
are emailed and check applications at `/admin/partners`. Partner plans (`Partner Standard`,
`Partner Pro`) are sold like the Milestone 13 plans: give them prices at `/admin/billing`. Until
they have prices, partners keep the free plan and no limits apply.

### Referrals (Milestone 15)

Customers ask to be introduced from an assessment; checked partners are offered the job and
accept it at `/partner/leads`. Nothing needs configuring for free referrals. To charge a fee
after a partner's included referrals, set a fee per category at `/admin/leads`. To let partners
buy credit, give the `Lead credits` product a price at `/admin/billing` (one purchase adds that
much credit). The consent wording lives in `apps/api/app/modules/leads/consent.json` and is
loaded by the migrate step on every deploy.

### Two-step sign-in for staff (Milestone 18)

From Milestone 18 the admin area needs two-step sign-in: a code from an authenticator app on
your phone after your password. After deploying, sign in, open **Account**, and under
**Security** choose **Turn on two-step sign-in**, scan the QR code with an authenticator app
(Google Authenticator, Microsoft Authenticator, 1Password), type the code it shows and save the
ten recovery codes somewhere safe (a password manager, or printed). Until then admin pages show
"Staff pages need two-step sign-in". Every staff member does the same.

Lost phone and recovery codes: on the server, check who is asking, then

```bash
docker compose -f docker-compose.prod.yml --env-file .env exec api \
  python -m app.cli auth reset-mfa --email person@example.com
```

turns it off for that person and signs them out everywhere. The authenticator secrets are
encrypted with a key derived from `SECRET_KEY`: changing `SECRET_KEY` means everyone has to set
two-step sign-in up again (reset each person as above). In an emergency
`STAFF_MFA_REQUIRED=false` in `.env` lifts the requirement (then rebuild); turn it back on
after.

New and changed passwords are checked against Have I Been Pwned's list of breached passwords
(`PASSWORD_BREACH_CHECK`, only five characters of a hash leave the server; if the service is
down the check is skipped). Every API route is limited per IP address
(`API_REQUESTS_PER_IP_PER_MINUTE`, 600, and `API_WRITES_PER_IP_PER_MINUTE`, 120); a 429 in
the logs from one address is that limit.

### Privacy requests and closed accounts (Milestone 19)

The site now has Terms of Use, a Privacy Policy and a contact page (links in every page's
footer). People can download their data and close their account from **Account**. Requests
from the contact page, and every closed account, appear at **Admin > Privacy**; each must be
answered within 30 days. Set `OPS_ALERT_EMAILS` in `.env` to get an email when one arrives;
**Admin > Operations** warns while any are open and alerts once one is overdue.

For a closed account, delete the personal workspace's projects and files (keep payment
records), email the person at the address shown, and mark the request done. Existing users are
asked once to agree to the Terms and Privacy Policy when they next use the app.

## 8. Persistent volumes

| Volume | Contents | Backed up |
|---|---|---|
| `pgdata` | PostgreSQL cluster (PG18 layout under `/var/lib/postgresql`) | Yes (nightly dump) |
| `redisdata` | Redis AOF (queues, rate counters) | No (rebuildable) |
| `caddy_data` | TLS certificates and ACME account | Optional |
| `uploads` | Customer files and generated reports (`STORAGE_BACKEND=local`, the default) | **Yes** (nightly archive) |
| `clamav_db` | ClamAV virus signatures | No (re-downloaded) |
| `backups` | Nightly dumps and file archives (14 days) | Copied off-host (§10) |

From Milestone 6 customer files live in the `uploads` volume by default. To keep them off the
server instead, set `STORAGE_BACKEND=s3` with `STORAGE_S3_BUCKET`, `STORAGE_S3_REGION`,
`STORAGE_S3_ENDPOINT_URL` (for non-AWS providers) and the access keys in `.env`; existing files
are not copied across automatically.

The `clamav` service needs about 1.5 GB of memory and takes a few minutes after its first start
to download signatures. Until it is ready uploads wait as "Checking for viruses" and are retried.

## 9. Migrations (Alembic)

* Every deploy runs `migrate` before the new `api` starts.
* Migrations must be **backwards compatible with the previous release** (expand → deploy →
  contract): add nullable columns / new tables first; drop or tighten only in a later release.
* Manual: `docker compose -f docker-compose.prod.yml run --rm migrate`.
* Rollback of code is preferred to `alembic downgrade` in production.

## 10. Backups

The `backup` service (Milestone 17, `infrastructure/backup/backup.sh`) runs every night at
02:30 Brisbane time. It writes a database dump (`db-<time>.dump`, `pg_dump -Fc`) and an
archive of uploaded files (`uploads-<time>.tgz`) to the `backups` volume, keeps 14 days of them
on the server and records each run (sizes, SHA-256) in the database. It also runs once straight
after its first start, so a deploy shows a backup within a minute. It holds the database
owner's password, so it sits on the internal network only and can't reach the internet.

| Setting (`.env`) | Default | Meaning |
|---|---|---|
| `BACKUP_TIMES` | `02:30` | Brisbane times, comma-separated (`02:30,14:30` for twice a day) |
| `BACKUP_KEEP_DAYS` | `14` | Days of backups kept on the server |
| `BACKUP_RESTORE_CHECK_DAY` | `7` | Day of the weekly restore check (1 Monday … 7 Sunday) |

```bash
docker compose -f docker-compose.prod.yml --env-file .env exec backup sh /usr/local/bin/backup.sh now
docker compose -f docker-compose.prod.yml --env-file .env exec backup sh /usr/local/bin/backup.sh list
docker compose -f docker-compose.prod.yml --env-file .env logs --tail 50 backup
```

**Off-site copies.** Backups on the server die with the server, so copy them off it. Either:

1. **Cloud storage (recommended).** Create a private bucket in an Australian region (AWS S3
   Sydney `ap-southeast-2`, Wasabi Sydney, or Backblaze B2) with encryption at rest and
   versioning or object lock, and a key that can only write to and read that bucket. Add to
   `.env` and redeploy:

   ```bash
   BACKUP_S3_BUCKET=approvalready-backups
   BACKUP_S3_REGION=ap-southeast-2
   BACKUP_S3_ENDPOINT_URL=          # only for Wasabi or B2, e.g. https://s3.ap-southeast-2.wasabisys.com
   BACKUP_S3_ACCESS_KEY_ID=...
   BACKUP_S3_SECRET_ACCESS_KEY=...
   ```

   Every 30 minutes the worker uploads new backups to `approvalready/db/` and
   `approvalready/uploads/` in the bucket (`BACKUP_S3_PREFIX`) and checks their size. Set the
   bucket's lifecycle rule to keep 35 daily copies (and monthly ones for a year if you like).
   Backups from before the bucket was set are copied too, as long as they are still on the
   server.
2. **Download them to your own computer** (no account needed, but you have to remember):

   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env cp backup:/backups ./backups-copy
   sudo chown -R deploy:deploy backups-copy
   ```

   then, on your computer, `scp -r deploy@<server>:/srv/approvalready/backups-copy .` and
   delete `backups-copy` on the server.

Point-in-time recovery (continuous WAL archiving with WAL-G or pgBackRest) is not set up: at
worst a day of changes is lost (less with two `BACKUP_TIMES`). Revisit when there are paying
customers whose day of work matters more than the extra moving part.

## 11. Restore checks and restoring

**Weekly restore check (automatic).** Every Sunday after the backup (and after the very first
one), the backup service restores the newest dump into a scratch database
(`<db>_restore_check`), checks that every table and the schema version came back and that the
files archive reads, records how long it took, and drops the scratch database. Run one now:

```bash
docker compose -f docker-compose.prod.yml --env-file .env exec backup sh /usr/local/bin/backup.sh restore-check
```

The result (tables, schema version, users, organisations, projects, files, seconds) shows at
`/admin/ops`. A failure is alerted like any other (§12).

**Restoring for real** (data lost or damaged, or a new server). This replaces the database and
the uploaded files with a backup, so everything since that backup is lost:

```bash
cd /srv/approvalready
docker compose -f docker-compose.prod.yml --env-file .env stop proxy web api worker scheduler
docker compose -f docker-compose.prod.yml --env-file .env exec backup sh /usr/local/bin/backup.sh list
# pick a pair with the same time, then:
docker compose -f docker-compose.prod.yml --env-file .env run --rm --no-deps \
  -v approvalready_uploads:/restore-uploads backup restore \
  db-<time>.dump uploads-<time>.tgz --yes
docker compose -f docker-compose.prod.yml --env-file .env run --rm migrate
docker compose -f docker-compose.prod.yml --env-file .env up -d --wait
curl -fsS https://api.<domain>/health/ready
```

On a new server, put the files from the bucket (or your computer) into the `backups` volume
first: start the stack once, then `docker compose ... cp ./db-<time>.dump backup:/backups/`
(and the matching `uploads-…tgz`). The restore creates the database's privilege group if it is
missing; `migrate` then recreates the application's login role. Run `verify-audit` afterwards
(§7) to confirm the audit log's hash chain survived.

## 12. Health checks, monitoring and alerts

| Endpoint | Meaning | Used by |
|---|---|---|
| `GET /health/live` (api) | Process serving | Docker HEALTHCHECK, Caddy upstream check |
| `GET /health/ready` (api) | PostgreSQL + Redis reachable; 503 otherwise | External uptime monitor |
| `GET /health/jobs` (api) | The scheduler's heartbeat is under 15 minutes old; 503 otherwise | External uptime monitor |
| `GET /version` (api) | Version, git SHA, environment | Deploy verification |
| `GET /api/health` (web) | Web serving, plus API status | Docker HEALTHCHECK, Caddy |
| `celery inspect ping` | Worker responsive | Docker HEALTHCHECK |

**Inside the app (Milestone 17).** Every 10 minutes the worker checks background jobs (the
heartbeat), the job queue, the latest backup (failed, or older than 26 hours), the weekly
restore check, the off-site copy (when set up) and free disk space. Platform admins see all of
it at `/admin/ops` ("Operations" in the admin menu). When a check starts failing, platform
admins get a notification and an email, as do the addresses in `OPS_ALERT_EMAILS`
(comma-separated, e.g. your own email); a check still failing is repeated every 12 hours, and
recovery is announced once. Warnings (no off-site copy yet, disk over 80 % full) are shown on
the page only.

**Outside the app.** The checks above run on the worker, so they can't report the worker or the
whole server being down. Add a free external monitor (UptimeRobot or Better Stack, checking
every 5 minutes, alerting your email or phone) on:

* `https://api.<domain>/health/ready` (database and Redis)
* `https://api.<domain>/health/jobs` (worker and scheduler)
* `https://<domain>/api/health` (web)

**Errors.** Set `SENTRY_DSN` (from a project at sentry.io, which offers EU data residency, or a
self-hosted GlitchTip) and redeploy: unhandled errors in the API and worker are reported with
their stack trace and request id, never cookies, headers, request bodies, query strings, user
details or IP addresses. Without it, errors are in the logs only:

```bash
docker compose -f docker-compose.prod.yml --env-file .env logs --since 1h api worker | grep -i error
```

Logs are JSON, one line per event, rotated at 5 × 20 MB per container.

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

## 15. Security testing (Milestone 17)

CI runs, on every pull request:

* **Browser tests** (Playwright, `apps/web/e2e`): the partner journey end to end, and a check
  that pages run no script the Content Security Policy blocks.
* **OWASP ZAP baseline scan** (passive) of the web app on that same stack. `.zap/rules.tsv`
  lists the findings that fail the build (missing security headers, CSP, cookie flags,
  sensitive data in URLs, XSS) and the accepted ones, with reasons; other warnings are
  reported only.
* **Dependency audits**: `pip-audit` over the API's locked runtime packages and
  `npm audit --omit=dev` over the web app's.

Content Security Policy: signed-in and auth pages use a per-request nonce; statically built
pages (home, guides, not-found) allow only the inline scripts hashed at build time
(`apps/web/scripts/csp-hashes.mjs`), so neither allows `'unsafe-inline'` scripts. Forms post
(`method="post"`), so nothing typed into a form can land in a URL or a log before the page's
scripts load.
