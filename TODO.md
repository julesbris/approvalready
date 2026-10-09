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

## Milestone 2 — Authentication, organisations, RBAC, audit ✅
- [x] `app_user`, `password_credential`, `auth_session`, `one_time_token`, `auth_identity` (schema for future SSO/passkeys)
- [x] Register (creates PERSONAL org), login, logout, logout everywhere, email verification (+ resend), password reset, password change
- [x] Opaque session cookies (`__Host-`), rotation with grace period, strict rotation on privilege change, idle/absolute expiry, revocation
- [x] CSRF (HMAC-bound double-submit token + Origin check), login throttling and auth rate limits (Redis), per-address email caps
- [x] Per-request CSP nonces for dynamic (auth/app) pages; static SEO pages keep the baseline policy (see Milestone 17)
- [x] `packages/shared-types` generated from the FastAPI OpenAPI schema; CI checks freshness
- [x] Organisations, members, invitations, roles (+ `ORG_ADMIN`), permissions, policy layer, no-escalation and last-admin rules
- [x] Append-only `audit_event` with hash chain, org audit endpoint, platform verify endpoint and CLI
- [x] Email provider interface (SMTP, console, memory) + dev mailbox (Mailpit)
- [x] Web: BFF proxy, sign in, register, verify email, forgot/reset password, accept invitation, account page
- [x] Tests: auth flows, throttling, expiry/rotation, CSRF/origin, tenant isolation, privilege rules, audit tamper detection
- [x] Moved to Milestone 3 (done there): RLS policies + `SET LOCAL app.current_org` with a dedicated non-superuser app DB role (needs the first tenant-owned tables to be meaningful)
- [ ] Moved to backlog: generic API-wide rate-limiting middleware (auth endpoints are limited now)

## Milestone 3 — Projects, questionnaires ✅
- [x] Separate app DB role (non-owner, no BYPASSRLS); migrations keep the owner role (`provision-db-role` CLI, readiness check in production)
- [x] RLS policies (ENABLE + FORCE) on every tenant table, transaction-local `app.current_org`, composite tenant foreign keys; RLS test harness and reviewed privilege map
- [x] Organisation management UI (create business, members, roles, invitations, leave, switch active organisation)
- [x] Customer entities: property (+ ownership), address, vessel, business profile (API)
- [x] Projects with vertical/status workflow and status history, tasks, reminders (stored; delivery below)
- [x] Questionnaire versioning (immutable published versions, submissions pinned), 12 question types, `visible_when` branching, validation, pruning of hidden answers, submit/reopen
- [x] Condition AST + three-valued evaluator (shared with Milestone 4), TypeScript mirror for instant branching, shared test vectors
- [x] Customer UI: projects, create project, select vertical, project workspace, guided questionnaire with review
- [x] Tests: branching, validation, versioning, RLS, tenant isolation, web components
- [ ] Moved to Milestone 11 (RentReady reminders need it first): reminder delivery via Celery beat + email/in-app notifications
- [ ] Moved to Milestone 5: entity UI (property/vessel/business pickers on projects), questionnaire prefill from entities
- [ ] Moved to Milestone 6: FILE question uploads (type exists; answers rejected until the upload pipeline lands)
- [ ] Moved to Milestone 4, then to backlog: questionnaire authoring in the admin UI (definitions stay reviewed JSON files synced on migrate)

## Milestone 4 — Sources, rules, assessments ✅
- [x] Source organisations/documents/references, verification workflow (verify against a snapshot, dispute, supersede, reopen; edits reset to unverified), append-only snapshots with change detection and review history
- [x] Condition AST (Pydantic), evaluator with three-valued logic, operator table, no eval (built in Milestone 3 for questionnaire branching); evaluation trace added
- [x] Rule sets with jurisdiction and scope condition, rule versioning (draft → published → retired, immutable once published, enforced by triggers), publish gate (valid condition, start date, outcomes, a basis source, usable sources, every test case passes)
- [x] Assessment runs on submitted answers, findings with confidence derivation, leaf-by-leaf trace, missing facts, pinned rule versions, facts hash and replay
- [x] Admin UI for sources (review queue, documents, snapshots, references, review actions) and rules (rule sets, draft editor, checks, try-it, publish/retire/new version); customer assessment report
- [x] Tests: every operator, nesting, unknown propagation, version pinning, reproducibility, confidence derivation, publish gate, RLS and privilege map for the new tables
- [ ] Moved to Milestone 5: `approval_requirement` / `evidence_requirement` tables and tasks created from findings (they need real PlanningReady rules to shape them)
- [ ] Moved to Milestone 11 (with reminder delivery): scheduled review reminders for references nearing `next_review_due` (overdue ones already show in the review queue and lower confidence)
- [ ] Moved to backlog: questionnaire authoring in the admin UI

## Milestone 5 — PlanningReady proof of concept ✅
- [~] One LGA (Cairns, QLD) × categories (secondary dwelling, subdivision first) with real sourced rules: content pack `planning_qld_cairns` (3 rule sets, 9 rules, 9 references) built from council's CairnsPlan 2016 fact sheets (October 2021) and the Planning Regulation 2017 (2022 secondary dwelling change). Every reference is an **unverified summary**: staff must capture each source, replace the extract with the exact wording and verify it. The planning scheme's tables of assessment (Part 5) and codes are not encoded yet
- [x] Outcome payloads (approval, evidence, referral categories, task) and rule set limitations
- [x] `approval_requirement` / `evidence_requirement` tables and tasks created from findings (moved from Milestone 4)
- [x] Property facts provider interface: `none` (default, production) and a development-only mock; no fabricated council/state APIs
- [x] Entity UI: property picker on planning/sell/rent projects; questionnaire prefill from the linked property and the provider (moved from Milestone 3)
- [x] Findings, requirements, referral categories ("who can help"), sources and limitations views
- [x] SEO: first sourced guide pages (`/guides`, Cairns secondary dwellings and subdivision)
- [ ] Next for Cairns: verify the pack's references against snapshots; encode Part 5 tables of assessment and Part 9 lot sizes from the current CairnsPlan 2016 text; add flooding/bushfire overlays
- [ ] Moved to backlog: vessel and business pickers (their verticals start in Milestones 8 and 9); `sitemap.xml` once the public site URL is configuration
- [ ] Moved to backlog: a real property facts provider (council or state planning mapping), only with a licensed, documented data source

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
- [ ] Security testing (ZAP baseline, dependency audit), CSP tightening (hash-based CSP for static pages)
- [ ] Kamatera go-live

## Backlog / decisions to revisit
- [ ] Questionnaire authoring in the admin UI (definitions are reviewed JSON files in the repo; revisit when non-developers need to edit them)
- [ ] Fetch source documents automatically for snapshots (manual capture only for now; no claims of live integration)
- [ ] Generic per-user/per-IP rate limiting for all API routes (auth routes already limited)
- [ ] Breached-password check (HIBP k-anonymity range API) at registration and reset
- [ ] MFA (TOTP) and passkeys via `auth_identity`; Google/Microsoft OIDC
- [ ] Send transactional email from the worker (outbox) instead of in-request
- [ ] `npm audit` flags `braces` (high) via `eslint-config-next` → `fast-glob`; dev-only lint tooling, not shipped in images. Re-check on next eslint-config-next release
- [ ] Brand/domain tables + Next.js host middleware (not needed until a second brand or partner surface; Milestone 14)
- [ ] Decide object storage vendor (Wasabi / Backblaze B2 / AWS S3 Sydney) — prefer an Australian region
- [ ] Obtain Australian legal advice on advice/referral/licensing boundaries before launch
- [ ] Review `julesbris/council-signon-system` for reusable council-domain assets
