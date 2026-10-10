# ApprovalReady

Australian approvals, compliance, property and funding platform. One modular SaaS system
behind six products: **PlanningReady**, **VesselReady**, **BusinessReady**, **GrantReady**,
**SellReady** and **RentReady** (the last two marketed together as **PropertyReady**).

The core rule: regulatory answers come from authoritative sources, through versioned
deterministic rules, with every result traceable to its source and labelled
`VERIFIED`, `LIKELY`, `REVIEW_REQUIRED` or `UNKNOWN`. AI explains and drafts; it never
decides what the law requires.

| Read | For |
|---|---|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | System design, diagrams, routing, partner subscriptions, lead matching |
| [`docs/DOMAIN_MODEL.md`](docs/DOMAIN_MODEL.md) | PostgreSQL domain model |
| [`docs/RISKS.md`](docs/RISKS.md) | Security and regulatory-data risks |
| [`docs/DEPLOY_KAMATERA.md`](docs/DEPLOY_KAMATERA.md) | Production deployment |
| [`TODO.md`](TODO.md) | Milestones and progress |

## Repository layout

```
apps/
  api/            FastAPI modular monolith (Python 3.14 in containers, 3.12+ locally)
  web/            Next.js 16 app: public site, customer app, partner and review portals
packages/
  shared-types/   TypeScript API contracts and shared enums
  ui/             Design tokens
infrastructure/
  caddy/          Reverse proxy config
docs/             Architecture, domain model, risks, deployment
scripts/          Developer scripts
tests/
  infrastructure/ Guards on deployment config (e.g. no public DB ports)
  fixtures/       Data shared by the API and web tests (condition evaluator vectors)
docker-compose.yml        Local development stack
docker-compose.prod.yml   Single-host production stack
```

## Quick start

Prerequisites: Docker with Compose v2, Node 22, [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env          # dev defaults work without edits
docker compose up --build     # db, redis, migrate, api, worker, scheduler, web
```

| URL | What |
|---|---|
| http://localhost:3000 | Web |
| http://localhost:8000/health/ready | API readiness (DB + Redis) |
| http://localhost:8000/docs | API docs (disabled in production) |
| http://localhost:3000/register | Create an account (emails land in Mailpit) |
| http://localhost:3000/projects | Projects and guided questionnaires (after signing in) |
| http://localhost:8025 | Mailpit: development mailbox |

Web with hot reload: `npm install && npm run dev:web` (expects the API on :8000).

## Tests

```bash
make test        # API (pytest, real Postgres 18 + Redis) and web (vitest)
make lint        # ruff, mypy, eslint, tsc
```

After changing API routes or schemas, regenerate the web's types with
`npm run generate:types` (CI fails if they are stale).

`scripts/test-services.sh up` starts throwaway Postgres and Redis containers bound to
loopback for the API suite; `down` removes them.

Browser end-to-end tests (Playwright, `apps/web/e2e`) drive the partner journey through a real
stack: `npm run test:e2e` (or `make test-e2e`) recreates an `approvalready_e2e` database on the
Postgres at 127.0.0.1:5432, migrates it, starts the API, a Celery worker and the production web
build as host processes, seeds the accounts and an assessed project, runs Playwright and stops
everything. Run the steps separately with `scripts/e2e.sh up|seed|test|down`; logs are in
`.e2e/`. Install the browser once with `npx playwright install chromium`.

## Status

Milestones 1 (infrastructure), 2 (authentication, organisations, RBAC, audit) and 3 (projects,
questionnaires, row-level security) are complete. See [`TODO.md`](TODO.md) for what is next.
