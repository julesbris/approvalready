# Current-State Assessment

_Date: 2026-10-04 · Author: lead architect (Claude) · Requested by Jules_

## 1. What exists

There was **no existing ApprovalReady codebase**. The GitHub account the project
can reach (`julesbris`) holds eight repositories (`barbell`, `tutor`, `retirement`,
`inspect`, `council-signon-system`, `askr`, `Notion-Voice-Notes`, `repository`).
None is named or shaped like ApprovalReady, so there was no README, architecture
document, environment file, Dockerfile or source to preserve.

Consequence: this repository is a **greenfield monorepo**. Nothing was deleted or
rewritten. `council-signon-system` may contain reusable council-domain ideas, but
it has not been inspected or imported; doing so is a deliberate future decision,
not an assumption.

## 2. Environment facts verified while building Milestone 1

| Item | Finding | Impact |
|---|---|---|
| Python 3.14 | `python:3.14-slim` image pulls and the API's dependencies install and run on it inside Docker. | Container images target 3.14. Local dev and CI also accept 3.12+ (`requires-python >=3.12`) so a laggard wheel never blocks contributors. |
| PostgreSQL 18 | `postgres:18-alpine` available. | Compose pins major 18. Note the PG18 image's data path changed to `/var/lib/postgresql` (versioned subdirectory); volumes are mounted there. |
| Redis | `redis:8-alpine` available. | Used for Celery broker/result backend, rate-limit counters and cache. |
| Node | Node 22 LTS, Next.js 16, React 19, TypeScript 7 available. | Web app built on Next.js App Router. |
| Docker | Docker 29 + Compose v2. | Single-host Compose deployment (Kamatera) as requested. |

## 3. Gaps against the vision (everything)

All six verticals, the partner portal, rules engine, provenance system, payments
and lead marketplace are unbuilt. The plan in `TODO.md` sequences them in the 17
milestones Jules specified. Milestone 1 (infrastructure skeleton) is implemented
in this change.

## 4. Key decisions taken at the start

1. **Modular monolith** — one FastAPI app with internal modules per bounded context
   (`identity`, `tenancy`, `projects`, `questionnaires`, `regulatory`, `rules`,
   `assessments`, `documents`, `review`, `billing`, `partners`, `leads`, `audit`,
   plus vertical modules). One Postgres database, schema-per-concern is **not**
   used initially (plain tables, prefixed by module), to keep migrations simple.
2. **One Next.js app** serving the public site, customer app, partner portal and
   review portal, distinguished by hostname → "surface" + "brand" resolution.
3. **Celery + Redis** for background work (mature, well understood, works on 3.14).
   Celery beat runs as a separate `scheduler` container so it can be singleton.
4. **psycopg 3** driver with SQLAlchemy 2 async engine for the API and a sync
   engine for Alembic and Celery tasks.
5. **Caddy** as reverse proxy (automatic HTTPS, simple config, works behind
   Cloudflare in Full (strict) mode).
