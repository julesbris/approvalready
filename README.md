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

Web with hot reload: `npm install && npm run dev:web` (expects the API on :8000).

## Tests

```bash
make test        # API (pytest, real Postgres 18 + Redis) and web (vitest)
make lint        # ruff, mypy, eslint, tsc
```

`scripts/test-services.sh up` starts throwaway Postgres and Redis containers bound to
loopback for the API suite; `down` removes them.

## Status

Milestone 1 (infrastructure) is complete. See [`TODO.md`](TODO.md) for what is next.
