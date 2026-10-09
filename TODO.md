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
- [x] Reminder delivery via Celery beat + email/in-app notifications (built in Milestone 11)
- [ ] Moved to Milestone 5: entity UI (property/vessel/business pickers on projects), questionnaire prefill from entities
- [x] Moved to Milestone 6: FILE question uploads (built there)
- [ ] Moved to Milestone 4, then to backlog: questionnaire authoring in the admin UI (definitions stay reviewed JSON files synced on migrate)

## Milestone 4 — Sources, rules, assessments ✅
- [x] Source organisations/documents/references, verification workflow (verify against a snapshot, dispute, supersede, reopen; edits reset to unverified), append-only snapshots with change detection and review history
- [x] Condition AST (Pydantic), evaluator with three-valued logic, operator table, no eval (built in Milestone 3 for questionnaire branching); evaluation trace added
- [x] Rule sets with jurisdiction and scope condition, rule versioning (draft → published → retired, immutable once published, enforced by triggers), publish gate (valid condition, start date, outcomes, a basis source, usable sources, every test case passes)
- [x] Assessment runs on submitted answers, findings with confidence derivation, leaf-by-leaf trace, missing facts, pinned rule versions, facts hash and replay
- [x] Admin UI for sources (review queue, documents, snapshots, references, review actions) and rules (rule sets, draft editor, checks, try-it, publish/retire/new version); customer assessment report
- [x] Tests: every operator, nesting, unknown propagation, version pinning, reproducibility, confidence derivation, publish gate, RLS and privilege map for the new tables
- [ ] Moved to Milestone 5: `approval_requirement` / `evidence_requirement` tables and tasks created from findings (they need real PlanningReady rules to shape them)
- [x] Built in Milestone 11 (weekly staff alert): scheduled review reminders for references nearing `next_review_due` (overdue ones already show in the review queue and lower confidence)
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
- [~] Moved to backlog: vessel and business pickers (business picker built in Milestone 8; vessel waits for Milestone 9); `sitemap.xml` once the public site URL is configuration
- [ ] Moved to backlog: a real property facts provider (council or state planning mapping), only with a licensed, documented data source

## Milestone 6 — Documents ✅
- [x] Object storage abstraction (local volume by default, S3), signed URLs for S3 and attachment-only downloads
- [x] Upload pipeline: size, count and rate limits, magic-byte MIME, zip checks for Office files, ClamAV scanning in a worker job, quarantine, retries and a stalled-job sweeper
- [x] Templates (reviewed files, immutable versions) + generated PDF/DOCX/HTML with the required report metadata (`PLANNING_ASSESSMENT`)
- [x] FILE question answers (moved from Milestone 3) and evidence linked to evidence requirements
- [x] Sharing documents with reviewers (classification) and reviewer accept/reject of evidence (done in Milestone 7)
- [ ] Moved to their verticals' milestones: templates other than `PLANNING_ASSESSMENT`

## Milestone 7 — Professional review ✅
- [x] Professionals, credentials, services; staff credential checks and activation
- [x] Review workflow states (request, assign, start, changes, resubmit, approve or complete, cancel, decline); comments; overrides (audited, append-only)
- [x] Reviewer workspace: shared files, evidence accept/reject, tasks; reports show the review and changes
- [ ] Moved to Milestone 13: paid reviews (`payment_id`, service prices)
- [ ] Backlog: credential evidence uploads, automatic assignment, review due-date reminders

## Milestone 8 — BusinessReady ✅
- [x] Business approval map (Required / Likely required / May apply / Not identified), on screen and as a `BUSINESS_APPROVAL_MAP` report
- [x] Business-type → marketplace category mapping (rules-driven): `marketplace_category` table from a reviewed file; outcomes may only name active categories
- [~] Sourced business rules for Queensland and Cairns: content pack `business_qld_cairns` (8 rule sets, 20 rules, 14 references), every reference an **unverified summary** to be captured and verified by staff
- [x] Business profile picker on business and grant projects; questionnaire prefill from the profile (moved from backlog)
- [ ] Next: verify the pack's references; other states and councils; signage, trade waste, noise and music licensing

## Milestone 9 — VesselReady ✅
- [x] Vessel profile: vessel picker on vessel projects, questionnaire prefill from the vessel, vessel certificates with expiry (moved from backlog)
- [~] Commercial pathway: content pack `vessel_au_qld` (2 rule sets, 12 rules, 16 references) from AMSA, Marine Order 504 (as made) and Queensland Government pages: domestic commercial vessel status, UVI, certificate of survey and non-survey approval (Exemption 02), certificate of operation (Exemption 03), SMS, simplified SMS, master's certificate of competency, Queensland recreational registration and licences. Every reference is an **unverified summary** to be captured and verified by staff
- [x] SMS builder: Marine Order 504 Schedule 1 headings with guidance, saved part by part, starting text from the vessel, downloadable `SMS` draft (PDF, DOCX, HTML)
- [x] Survey checklist and registration prep: reviewed checklists (initial survey, non-survey approval, certificate of operation, UVI, Queensland registration) added to a project by the rules that name them or by the customer
- [x] `VESSEL_PATHWAY` report and the approval map on vessel assessments
- [ ] Next: verify the pack's references; read Exemption 02 and 03 schedules and Marine Orders 503 and 505 into rules (survey frequency, crewing, which certificate each crew member needs); Queensland smooth and partially smooth water boundaries; other states' registration
- [x] Built in Milestone 11: reminders 60 and 14 days before a vessel certificate expires

## Milestone 10 — GrantReady ✅
- [x] Grant programs and rounds (platform data kept by staff in `/admin/grants`); every round's status and dates cite a source reference, and the dates refine the status (an open round past its closing date reads as closed)
- [x] Eligibility rules: each program's criteria are an ordinary `GRANT` rule set (one rule per criterion, matching when met; `applies_when` is who can apply)
- [x] Match statuses per program on every grant assessment: strong match, possible match, needs information, not eligible (`grant_match`, append-only); no success percentages
- [x] Grant profile: the `grant.general` questionnaire (v2 adds ABN age, GST, entity type, turnover, export stage, innovation and National Reconstruction Fund areas) with prefill from the linked business profile (moved from Milestone 8, which only prefilled `business.*` facts)
- [x] `GRANT_ELIGIBILITY` report (PDF, DOCX, HTML)
- [~] Content pack `grants_au_qld` (3 programs, 3 rule sets, 14 rules, 9 references): Export Market Development Grants (Austrade), the Industry Growth Program (business.gov.au) and Queensland's Business Growth Fund. Every reference is an **unverified summary**. None of the three was open to applications when read on 2026-10-09
- [x] Built in Milestone 11: alerts when a matched program's round opens within 7 days or is about to close
- [ ] Moved to Milestone 12: `GRANT_DRAFT` application drafting (needs the AI layer)
- [ ] Next: verify the pack's references; read each program's guidelines (not just its web pages) into rules; more programs (state and council grants, Cairns); a program-creation form in the admin screens (the API and the pack create them today); reviewer overrides are not applied to matches yet

## Milestone 11 — PropertyReady ✅
- [x] SellReady: sale project lifecycle, checklists, disclosure workflow (contract needs disclosure given or not needed), document vault, offers, enquiries, settlement reminders
- [x] RentReady: compliance checklists, listings, applications with document checks (no AI selection or scoring), tenancies, inspections (phone-first, photos), maintenance, bond, lease-end and rent-review reminders
- [x] Reminder delivery (Celery beat), in-app notifications and email, header bell and `/notifications`
- [x] Rules-driven cross-sell offers (`cross_sell` on `CROSS_SELL` outcomes, shown on assessment reports)
- [~] Content pack `property_qld` (2 rule sets, 20 rules, 21 references, 6 checklists). Every reference is an **unverified summary**
- [ ] Next: verify the pack's references (open points: entry notice period for showing buyers, disclosure timing rules); other states; Form 1 entry condition report and disclosure statement generation; notification preferences

## Milestone 12 — AI abstraction and drafting ✅
- [x] `AIProvider` protocol (`generate_structured`, `generate_text`); providers `none` (default), `mock` (refused in production) and `anthropic` (official SDK, JSON structured output, refusal fallback), chosen by `AI_PROVIDER`
- [x] Prompt registry: reviewed prompt files synced on migrate into immutable `prompt_version` rows
- [x] Pydantic output validation (versioned schemas), finding-reference post-check, and a grounding check that rejects numbers and links not in the input
- [x] `ai_job` and append-only `ai_provider_log` (tokens, cost, latency, outcome); worker job with retries and the stalled-job sweep; per-user hourly limit; identical input reuses the draft
- [x] Plain-language explanation of an assessment's findings and grant application notes, shown as "AI draft" panels; staff usage and prompts at `/admin/ai`
- [ ] Next: AI text in generated reports (`generated_document.ai_job_id`), document extraction from uploads (with the S3 safeguards), per-task model choice, an evaluation set for the prompts

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
