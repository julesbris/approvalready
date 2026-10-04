# TODO / Milestones

Legend: `[x]` done · `[ ]` not started · `[~]` partial. Each milestone ends with green
tests and updated docs before the next starts.

## Milestone 1 — Infrastructure ✅
- [x] Monorepo layout (`apps/api`, `apps/web`, `packages/*`, `infrastructure`, `docs`, `scripts`, `tests`)
- [x] FastAPI app factory, settings, JSON logging, request IDs
- [x] Security headers, strict CORS, trusted hosts
- [x] SQLAlchemy 2 async engine (psycopg 3), Redis client
- [x] Alembic configured, baseline migration (`pgcrypto`, `citext`)
- [x] Health: `/health/live`, `/health/ready` (DB + Redis), `/version`
- [x] Celery worker + beat scheduler skeleton with `system.ping`
- [x] Next.js 16 web app (App Router, TS strict), `/api/health`
- [x] `packages/shared-types`, `packages/ui` tokens
- [x] Dockerfiles (multi-stage, non-root), `docker-compose.yml`, `docker-compose.prod.yml`, Caddyfile
- [x] Prod compose: only proxy publishes ports; db/redis internal (tested)
- [x] pytest suite (unit + integration against real Postgres/Redis), vitest for web
- [x] GitHub Actions CI
- [x] `docs/DEPLOY_KAMATERA.md` initial runbook
- [x] Prod stack smoke-tested end to end through Caddy (TLS, API ready, web, worker round trip, DB/Redis unreachable from host and proxy)

## Milestone 2 — Authentication, organisations, RBAC, audit
- [ ] `app_user`, `password_credential`, `session`, `one_time_token`, `auth_identity`
- [ ] Register (creates PERSONAL org), login, logout, email verification, password reset
- [ ] Opaque session cookies (`__Host-`), rotation, idle/absolute expiry, revocation
- [ ] CSRF double-submit, login throttling (Redis), rate limiting middleware
- [ ] Per-request CSP nonces in Next.js so `script-src 'unsafe-inline'` can be removed
- [ ] Generate `packages/shared-types` from the FastAPI OpenAPI schema
- [ ] Organisations, members, invitations, roles, permissions, policy layer
- [ ] RLS policies + `SET LOCAL app.current_org`
- [ ] Append-only `audit_event` with hash chain
- [ ] Email provider interface + dev mailbox (Mailpit)
- [ ] Tests: auth flows, throttling, tenant isolation harness

## Milestone 3 — Projects, questionnaires
- [ ] Customer entities: property, address, vessel, business profile
- [ ] Projects with vertical/status, tasks, reminders
- [ ] Questionnaire versioning, all question types, `visible_when` branching, validation
- [ ] Customer UI: create project, select vertical, guided questionnaire
- [ ] Tests: branching, validation, versioning

## Milestone 4 — Sources, rules, assessments
- [ ] Source organisations/documents/references, verification workflow, snapshots
- [ ] Condition AST (Pydantic), evaluator with three-valued logic, operator table, no eval
- [ ] Rule versioning, publish gate (test cases pass, sources linked)
- [ ] Assessment runs, findings, confidence derivation, trace
- [ ] Admin UI for sources and rules
- [ ] Tests: every operator, nesting, unknown propagation, version pinning, reproducibility

## Milestone 5 — PlanningReady proof of concept
- [ ] One LGA (Cairns, QLD) × categories (secondary dwelling, subdivision first) with real sourced rules
- [ ] Property facts provider interface (mock; no fabricated council/state APIs)
- [ ] Findings, requirements, referral categories, sources and limitations views
- [ ] SEO: first sourced guide pages

## Milestone 6 — Documents
- [ ] Object storage abstraction (local/S3), signed URLs
- [ ] Upload pipeline: limits, magic-byte MIME, malware-scan interface (ClamAV), quarantine
- [ ] Templates + generated PDF/DOCX/HTML with required report metadata

## Milestone 7 — Professional review
- [ ] Professionals, credentials, services; review workflow states; comments; overrides (audited)

## Milestone 8 — BusinessReady
- [ ] Business approval map (Required / Likely required / May apply / Not identified)
- [ ] Business-type → marketplace category mapping (rules-driven)

## Milestone 9 — VesselReady
- [ ] Vessel profile, commercial pathway, SMS builder, survey checklist, registration prep

## Milestone 10 — GrantReady
- [ ] Grant profiles, programs, rounds (sourced dates), eligibility rules, match statuses

## Milestone 11 — PropertyReady
- [ ] SellReady: sale project lifecycle, checklist, disclosure workflow, vault, offers, enquiries
- [ ] RentReady: compliance checklists, listings, applications (no AI selection), tenancy, inspections (mobile), maintenance, reminders
- [ ] Rules-driven cross-sell offers

## Milestone 12 — AI abstraction and drafting
- [ ] `AIProvider` protocol, configurable providers, mock provider
- [ ] Prompt registry, Pydantic output validation, finding-reference post-check, provider log

## Milestone 13 — Customer payments
- [ ] Products/prices/features tables, Stripe checkout + portal, webhooks (idempotent), entitlements

## Milestone 14 — Partner accounts, subscriptions, dashboard
- [ ] Partner application + staff verification, categories, service areas, credentials
- [ ] Plans/features (data), Stripe partner subscriptions, PAST_DUE grace logic
- [ ] Partner portal surface on `partners.` host

## Milestone 15 — Lead engine
- [ ] Referral consent (versioned text, fields released)
- [ ] Matching (hard filters + explainable ranking), release policy, claiming with row locks
- [ ] Contact locking/release, lead fees + credits ledger, outcomes
- [ ] Partner E2E Playwright test (16 steps) + negative cases

## Milestone 16 — Marketplace analytics
- [ ] Per-partner analytics; k-anonymous aggregates only

## Milestone 17 — Production hardening
- [ ] Backups (pg_dump + WAL to off-site S3), restore drills
- [ ] Monitoring (uptime, logs, metrics, error tracking), alerting
- [ ] Security testing (ZAP baseline, dependency audit), CSP tightening
- [ ] Kamatera go-live

## Backlog / decisions to revisit
- [ ] `npm audit` flags `braces` (high) via `eslint-config-next` → `fast-glob`; dev-only lint tooling, not shipped in images. Re-check on next eslint-config-next release
- [ ] Brand/domain tables + Next.js host middleware (planned for Milestone 2–3 alongside surfaces)
- [ ] Decide object storage vendor (Wasabi / Backblaze B2 / AWS S3 Sydney) — prefer an Australian region
- [ ] Obtain Australian legal advice on advice/referral/licensing boundaries before launch
- [ ] Review `julesbris/council-signon-system` for reusable council-domain assets
