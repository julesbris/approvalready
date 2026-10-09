# ApprovalReady Architecture

ApprovalReady is one modular SaaS platform for Australian approvals, compliance,
property and funding. Six customer products (PlanningReady, VesselReady,
BusinessReady, GrantReady, SellReady, RentReady; the last two marketed as
PropertyReady) share one backend, one database, one frontend application and one
deployment.

Companion documents:

| Document | Contents |
|---|---|
| [`docs/ASSESSMENT.md`](docs/ASSESSMENT.md) | Current-state repository assessment |
| [`docs/DOMAIN_MODEL.md`](docs/DOMAIN_MODEL.md) | PostgreSQL domain model (all entities, keys, constraints) |
| [`docs/RISKS.md`](docs/RISKS.md) | Security and regulatory-data risks with mitigations |
| [`docs/DEPLOY_KAMATERA.md`](docs/DEPLOY_KAMATERA.md) | Production deployment runbook |
| [`TODO.md`](TODO.md) | Milestones and status |

---

## 1. Core principle: the LLM is never the authority

```
AUTHORITATIVE SOURCE  (legislation, planning scheme, AMSA, council, grant guidelines)
        ↓  captured by staff with provenance (URL, version, clause, page, retrieved/effective dates)
STRUCTURED REGULATORY DATA  (SourceDocument → SourceReference)
        ↓  encoded and reviewed by humans
VERSIONED RULES ENGINE  (RuleSet → Rule → RuleVersion, immutable once published)
        ↓  pure, deterministic evaluation over questionnaire answers + entity facts
DETERMINISTIC RESULT  (Assessment → AssessmentFinding with confidence)
        ↓  read-only input
AI EXPLANATION / DOCUMENT GENERATION  (schema-validated, cites finding IDs only)
```

Rules:

* A finding can only be `VERIFIED` when every contributing rule version links to a
  source reference whose verification status is `VERIFIED` and is in force on the
  assessment date. Otherwise it degrades to `LIKELY`, `REVIEW_REQUIRED` or `UNKNOWN`.
* The AI layer receives findings + sources as data and may only reference findings
  by ID. Post-generation validation rejects output that introduces fees, dates,
  clause numbers or requirements not present in the input findings.
* Trace chain stored for every result:
  `Customer result → AssessmentFinding → RuleVersion → RuleSource → SourceReference → SourceDocument`.

## 2. System architecture

### 2.1 Runtime components

| Component | Tech | Responsibility |
|---|---|---|
| `proxy` | Caddy 2 | TLS termination (or Cloudflare origin cert), host routing, security headers, request size limits. The only container with published ports (80/443). |
| `web` | Next.js 16 (App Router, TypeScript, React 19) | Public marketing/SEO pages (SSG/ISR), customer app, partner portal, review portal, admin. Resolves hostname → surface + brand. Server components call the API over the internal network. |
| `api` | FastAPI on Uvicorn, Python 3.14 | All business logic and authorisation. Modular monolith. |
| `worker` | Celery | Document generation, AI jobs, malware scanning, notifications, lead matching fan-out, Stripe webhook post-processing. |
| `scheduler` | Celery beat | Reminders (rent review, lease renewal, bond), subscription grace-period expiry, lead expiry, source re-verification reminders. Exactly one instance. |
| `db` | PostgreSQL 18 | System of record. Internal network only. |
| `redis` | Redis 8 | Celery broker/results, rate limiting, short-lived cache. Internal network only, password protected. |
| Object storage | Local volume in dev; S3-compatible in prod (MinIO/Wasabi/Backblaze/AWS) | Uploaded and generated documents. Private by default, signed URLs. |

### 2.2 Backend module layout (modular monolith)

```
apps/api/app/
  core/            config, logging, db, redis, security headers, request context
  api/             HTTP routers (health now; v1 routers per module later)
  modules/
    identity/      users, credentials, sessions, email verification, password reset
    tenancy/       organisations, members, roles, permissions, policy checks
    audit/         append-only audit events
    projects/      projects, verticals, statuses, tasks, reminders
    entities/      properties, ownership, vessels, business profiles, customer profiles
    questionnaires/
    regulatory/    source documents, references, verification workflow
    rules/         rule sets, versions, condition AST, evaluator (no eval)
    assessments/   assessment runs, findings, requirements
    documents/     uploads, scanning, storage, generated documents, templates
    ai/            provider abstraction, prompt registry, job log, output validation
    review/        professionals, credentials, review workflow
    billing/       products, prices, Stripe, subscriptions, entitlements, credits
    partners/      partner orgs, plans, applications, service areas, preferences
    leads/         lead creation, matching, release, claiming, outcomes
    consent/       consent text versions, referral consents
    notifications/
    branding/      domain → brand → surface configuration
    verticals/     planning, vessel, business, grants, sell, rent (thin: workflow + rule-pack wiring)
  worker/          Celery app and task registration
```

Module rules: modules talk through service functions, not each other's tables.
Each module owns its tables and Alembic migrations live in one linear history.

### 2.3 Mermaid architecture diagram

```mermaid
flowchart TB
    subgraph Internet
        U[Customers]:::ext
        P[Partners]:::ext
        R[Professional reviewers]:::ext
        S[Staff / Admin]:::ext
        STRIPE[Stripe]:::ext
        AIP[AI providers<br/>configurable]:::ext
        SRC[Authoritative sources<br/>legislation, councils, AMSA,<br/>grant guidelines]:::ext
    end

    CF[Cloudflare<br/>DNS, CDN, WAF]
    U & P & R & S --> CF
    CF --> CADDY

    subgraph Host["Kamatera Ubuntu host (Docker Compose)"]
        CADDY[Caddy<br/>TLS, host routing, headers<br/>ports 80/443 only]
        subgraph app_net["internal network"]
            WEB[Next.js web<br/>public · app · partners · review · admin<br/>brand resolved from Host]
            API[FastAPI modular monolith<br/>authN/authZ, tenancy, rules,<br/>assessments, billing, leads, audit]
            WORKER[Celery worker<br/>documents, AI jobs, scanning,<br/>notifications, matching]
            BEAT[Celery beat<br/>reminders, expiry, grace periods]
            DB[(PostgreSQL 18)]
            REDIS[(Redis 8)]
            SCAN[Malware scanner<br/>ClamAV, interface]
        end
    end

    OBJ[(S3-compatible<br/>object storage)]

    CADDY --> WEB
    CADDY -->|api.* host| API
    WEB -->|server-side fetch| API
    API --> DB
    API --> REDIS
    API -->|signed URLs| OBJ
    WORKER --> DB
    WORKER --> REDIS
    WORKER --> OBJ
    WORKER --> SCAN
    WORKER -->|schema-validated calls| AIP
    BEAT --> REDIS
    STRIPE -->|signed webhooks| CADDY
    API -->|checkout, portal| STRIPE
    SRC -.->|captured by staff with provenance<br/>no fabricated integrations| API

    classDef ext fill:#f4f4f5,stroke:#71717a,color:#18181b;
```

Regulatory data flow:

```mermaid
flowchart LR
    SD[SourceDocument<br/>org, jurisdiction, URL,<br/>version, effective/expiry] --> SR[SourceReference<br/>section, clause, page,<br/>extracted text, verification]
    SR --> RS[RuleSource]
    RS --> RV[RuleVersion<br/>immutable, condition AST]
    RV --> AF[AssessmentFinding<br/>outcome + confidence]
    QR[QuestionResponses<br/>+ entity facts] --> AF
    AF --> A[Assessment]
    A --> AI[AI explanation<br/>cites finding IDs only]
    A --> GD[GeneratedDocument<br/>sources, assumptions,<br/>review status]
    AF --> RQ[ReviewRequest<br/>overrides audited]
```

## 3. Database / domain architecture (summary)

Full model: [`docs/DOMAIN_MODEL.md`](docs/DOMAIN_MODEL.md). Conventions:

* UUID primary keys (`uuid` type; v7 generated application-side for index locality).
* Every table: `created_at`, `updated_at` (timestamptz, UTC), `created_by` (nullable FK to user).
  Soft-deletable tables add `deleted_at`. Audit and finding tables are append-only (no update/delete grants for the app role on `audit_event`).
* Tenancy: every tenant-owned row carries `organisation_id`. Every user gets a personal organisation on registration, so "personal account" is just an organisation of kind `PERSONAL`. This removes the user-or-org polymorphism everywhere else. Tenant tables are also protected by Postgres row-level security (see §3.1).
* Enumerations stored as `text` with `CHECK` constraints (cheaper to evolve than PG enums) and mirrored as Python `StrEnum`.
* Money as `bigint` cents + `currency char(3)` (default `AUD`). Prices never hard-coded.
* JSONB only for genuinely schemaless payloads (rule condition AST, answer values, AI output); everything queried or joined is a column.

Bounded contexts and their main aggregates:

| Context | Aggregates |
|---|---|
| Identity & tenancy | User, Credential, Session, Organisation, OrganisationMember, Role, Permission |
| Customer entities | CustomerProfile, BusinessProfile, Property, PropertyOwnership, Vessel |
| Projects | Project (vertical, status), Task, Reminder |
| Questionnaires | Questionnaire → QuestionnaireVersion → QuestionVersion → QuestionOption; QuestionnaireSubmission → QuestionResponse |
| Regulatory | SourceDocument → SourceReference |
| Rules | RuleSet → Rule → RuleVersion (+ RuleCondition AST, RuleOutcome, RuleSource) |
| Assessments | Assessment → AssessmentFinding → ApprovalRequirement / EvidenceRequirement |
| Documents | UploadedDocument, Evidence, DocumentTemplate(+Version), GeneratedDocument |
| AI | AIJob, AIProviderLog, PromptVersion |
| Review | Professional, ProfessionalCredential, ProfessionalService, ReviewRequest, ReviewDecision, FindingOverride |
| Billing | Product, Price, Payment, Subscription, Entitlement, CreditLedgerEntry, InvoiceReference, StripeEvent |
| Partners | PartnerOrganisation (extends Organisation), PartnerApplication, PartnerPlan, PlanFeature, PartnerSubscription, PartnerCategory, PartnerServiceArea, PartnerLeadPreference, ProviderProfile |
| Leads | Lead, LeadMatch, LeadClaim, LeadStatusEvent, LeadReleasePolicy, QuoteRequest, Quote |
| Consent | ConsentTextVersion, Consent (service/marketing), ReferralConsent |
| Grants | GrantProfile, GrantProgram, GrantRound, GrantEligibilityRule (→ RuleVersion), GrantMatch |
| Property | SaleProject, SaleOffer, RentalPropertyProfile, Tenancy, TenantApplication, Inspection, InspectionItem, PropertyMaintenanceItem |
| Platform | AuditEvent, Notification, Brand, BrandDomain, FeatureFlag |

### 3.1 Database roles and row-level security (built in Milestone 3)

Application authorisation (membership and permission checks on every `/organisations/{id}`
route) is the first line. Row-level security is the second: if application code ever forgets a
tenant filter, the database still returns nothing from other organisations.

| Role | Used by | Can |
|---|---|---|
| Owner (`POSTGRES_USER`) | `migrate` only (`MIGRATION_DATABASE_URL`) | Owns every table; runs Alembic, `provision-db-role`, `questionnaires sync`. |
| `approvalready_rw` (NOLOGIN group) | — | Holds the application's grants, table by table (reviewed map in the `0003` migration, asserted by `tests/test_rls.py`). Reference and questionnaire-definition tables are read-only; `audit_event` and `project_status_event` are insert/select only. |
| `approvalready_app` (LOGIN, `APP_DB_USER`) | `api`, `worker` (`DATABASE_URL`) | Member of `approvalready_rw`; `NOSUPERUSER NOBYPASSRLS`, owns nothing. `/health/ready` fails in production if this ever stops being true. |

* Every table with `organisation_id` (the `TenantMixin` tables) has `ENABLE` and `FORCE ROW
  LEVEL SECURITY` and one policy, `tenant_isolation`:
  `organisation_id = nullif(current_setting('app.current_org', true), '')::uuid` for both
  `USING` and `WITH CHECK`. With no tenant bound, nothing is visible and nothing can be written.
* The tenant is bound per transaction (`set_config('app.current_org', …, true)`), only after the
  membership check in `require_org_permission`. A SQLAlchemy `after_begin` listener re-applies it
  at the start of every transaction in the same request, and the transaction-local setting
  cannot leak to the next user of a pooled connection.
* Foreign-key checks bypass RLS, so tenant-to-tenant references are composite:
  `(organisation_id, project_id) → project(organisation_id, id)`. A row can never point at
  another organisation's row, even when written by the owner.
* Identity and tenancy tables (users, sessions, memberships) are not tenant-scoped: they are read
  before a tenant is known, and stay protected by application authorisation.

## 4. Domain-routing architecture

One Next.js deployment and one API serve every hostname. Routing is **data**, not code.

```
Request Host ─▶ Caddy (TLS; all brand hosts → web, api.* → api)
            ─▶ Next.js middleware: resolve Host → { brand, surface }
            ─▶ rewrite to /(surface)/... route group, inject brand into request headers
            ─▶ server components read brand (logo, name, theme accent, metadata, SEO, canonical host)
```

**Surfaces** (each a Next.js route group with its own layout/shell/login):

| Surface | Default host | Notes |
|---|---|---|
| `public` | `approvalready.com.au` | Marketing, vertical landing pages, SEO guides, `/partners` explainer. SSG/ISR. |
| `app` | `app.approvalready.com.au` | Customer dashboard (projects, questionnaires, documents, quotes). |
| `partners` | `partners.approvalready.com.au` | Partner login, dashboard, lead inbox, billing. |
| `review` | `review.approvalready.com.au` | Professional review queue. |
| `admin` | `app.approvalready.com.au/admin` | Staff tools; additionally IP-allowlist capable at Caddy. |
| `api` | `api.approvalready.com.au` | FastAPI; never served by Next.js. |

**Brand configuration** (`brand`, `brand_domain` tables; cached in Redis and in the web
process, with a static fallback file for build-time SSG):

| Field | Example |
|---|---|
| `brand.key` | `approvalready`, `planningready` |
| `brand.product_name`, `logo_asset`, `theme_accent`, `default_vertical` | |
| `brand.seo` (title template, description, OG image) | |
| `brand_domain.hostname` | `planningready.com.au` |
| `brand_domain.mode` | `PRIMARY` (serve), `REDIRECT` (301 to `redirect_target`), `ALIAS` (serve but canonical points elsewhere) |
| `brand_domain.surface` | `public`, `app`, `partners`, `review` |
| `brand_domain.redirect_target` | `https://approvalready.com.au/planning` |

Recommended default (concentrates SEO authority): the parent domain serves everything;
vertical domains (`planningready.com.au`, `vesselready.com.au`, `grantready.com.au`,
`rentready.com.au`, …) are `REDIRECT` rows → `approvalready.com.au/<vertical>`.
Domain availability is not assumed; adding a domain is an admin data change plus a DNS
record and a Caddy on-demand-TLS allowlist entry (Caddy asks the API
`/internal/tls/allowed?domain=` before issuing a certificate).

Cookies: session cookies are host-only per surface (`__Host-` prefix), so a partner
session on `partners.` is not sent to `app.`. The API is called server-side from Next.js
(BFF pattern) for authenticated pages, so the browser never holds a bearer token.

## 5. Authentication and authorisation (built in Milestone 2)

```mermaid
sequenceDiagram
    actor B as Browser
    participant W as Next.js (app host)
    participant A as FastAPI
    participant DB as PostgreSQL
    participant R as Redis
    B->>W: POST /api/v1/auth/login (same origin)
    W->>A: POST /v1/auth/login (Origin, XFF forwarded)
    A->>R: per-account / per-IP failure counters
    A->>DB: Argon2id verify, insert auth_session (token hash), audit_event
    A-->>W: Set-Cookie __Host-ar_session (HttpOnly) + __Host-ar_csrf
    W-->>B: Set-Cookie relayed unchanged (host-only cookies on the app host)
    B->>W: POST /api/v1/... + X-CSRF-Token header
    W->>A: cookie + CSRF header
    A->>DB: resolve session → user → membership → role → permission
```

* **Passwords:** Argon2id (`argon2-cffi` defaults, RFC 9106 profile), rehash on login when
  parameters change. Minimum 12 characters, maximum 256, not equal to the email. Unknown
  emails still run an Argon2 verification against a dummy hash (timing).
* **Sessions:** opaque 256-bit tokens; only SHA-256 hashes are stored (`auth_session`).
  Idle timeout 30 min (sliding, written at most once a minute), absolute lifetime 14 days,
  periodic rotation every 60 min with a 60 s grace period for in-flight requests, strict
  rotation (no grace) on privilege changes (organisation switch, password change).
  Server-side revocation: logout, logout everywhere, password change (other sessions),
  password reset (all sessions). No JWTs anywhere, nothing in browser storage.
* **Cookies:** `__Host-ar_session` (HttpOnly, Secure, SameSite=Lax, Path=/, no Domain) and
  `__Host-ar_csrf` (readable by script). `COOKIE_SECURE=false` (dev/test only, refused in
  production) drops the prefix so plain-HTTP localhost works.
* **BFF:** the browser only calls the web origin. `/api/v1/*` in Next.js proxies an
  allowlist of API areas (`auth`, `organisations`, `invitations`, `admin`), forwarding only
  allowlisted headers and relaying `Set-Cookie`. Server components fetch the session with
  the user's cookies (`src/lib/session.ts`).
* **CSRF:** SameSite=Lax, plus a double-submit token for every cookie-authenticated
  state change. The token is `HMAC(SECRET_KEY, session_id)`, so it survives token rotation
  and cannot be forged by planting a cookie. An Origin check rejects state-changing requests
  from origins outside `CORS_ORIGINS` (covers login CSRF, before a session exists).
* **Enumeration resistance:** register, resend-verification and password-reset requests
  always return `202 {"status":"accepted"}`. Registering an existing address emails that
  address instead of returning an error. Login says "email not verified" only after a
  correct password.
* **Throttling (Redis, fixed windows):** 5 failed logins per account and 30 per IP per
  15 min, then 429 with `Retry-After`; 30 unauthenticated auth requests per IP per minute;
  3 emails of one kind per address per hour (no mail bombing). Email addresses are hashed
  in Redis keys.
* **Email verification and reset:** single-use hashed tokens in `one_time_token`; issuing
  a new link invalidates older ones. Login requires a verified email. Reset links expire
  after 60 min and sign the user out everywhere.
* **Email delivery:** `EmailProvider` protocol with SMTP (Mailpit in dev, any relay in
  production, verified STARTTLS), console and in-memory implementations.
* **Future SSO/passkeys:** `auth_identity (provider, subject)` exists; Google/Microsoft
  OIDC and WebAuthn plug in by creating sessions through the same `create_session`.

**Organisations and RBAC.** Every user gets a `PERSONAL` organisation at registration with
`CUSTOMER` + `ORG_ADMIN`. Users can create `BUSINESS` and `PROFESSIONAL_PRACTICE`
organisations; `PARTNER` organisations arrive through the partner application flow
(Milestone 14) and the `PLATFORM_ADMIN` organisation is bootstrapped by CLI only
(`python -m app.cli grant-platform-role`). Members join by emailed, single-use invitation
bound to the invited address.

| Role | Granted in | Permissions (summary) |
|---|---|---|
| `CUSTOMER` | PERSONAL, BUSINESS | org read, members read, project read/write |
| `ORG_ADMIN` | PERSONAL, BUSINESS, PROFESSIONAL_PRACTICE | org update, members manage, invitations, org audit |
| `PROFESSIONAL` | PROFESSIONAL_PRACTICE | review.perform, project read |
| `PARTNER_USER` | PARTNER | lead read/claim |
| `PARTNER_ADMIN` | PARTNER | partner user + org admin |
| `STAFF` | PLATFORM_ADMIN | platform users/organisations read, source.verify |
| `ADMIN` | PLATFORM_ADMIN | staff + platform audit, rule.publish, org admin |
| `SUPERADMIN` | PLATFORM_ADMIN | admin + platform.roles.manage |

`ORG_ADMIN` is an addition to the brief's role list: business and practice owners need to
manage their members without being given partner or platform roles. Rules enforced in the
service layer (and the first one again by a database trigger):

1. A role can only be granted in the organisation kinds it lists.
2. No escalation: an actor can only grant roles whose permissions are a subset of their
   own, and can only change or remove members whose permissions are a subset of theirs.
3. Every organisation keeps at least one active member with `org.members.manage`.

Authorisation lives in `app/api/deps.py`. Routes under `/v1/organisations/{id}` resolve the
caller's *current* membership of that organisation on every request (so removal or demotion
takes effect immediately) and answer **404** when there is none, so other tenants'
organisations are indistinguishable from non-existent ones. Platform permissions apply only
while the session's active organisation is the `PLATFORM_ADMIN` organisation (explicit
context switch, audited). Postgres Row-Level Security is the planned second layer once the
first tenant-owned business tables land (Milestone 3; see `docs/RISKS.md` S1).

**Audit.** `audit_event` is append-only: `BEFORE UPDATE/DELETE/TRUNCATE` triggers reject
changes for every role, including the owner. Each row stores `hash = SHA-256(canonical JSON
of the row + prev_hash)`; writers serialise on a transaction-scoped advisory lock so `seq`
order equals chain order, and the event commits in the same transaction as the change it
records. `python -m app.cli verify-audit` and `GET /v1/admin/audit/verify` (platform
`platform.audit.read`) recompute the chain and report the first broken row. Audited actions
include registration, verification, login success/failure (email hashed, never stored in
clear), logout, password reset/change, organisation switch, organisation create/update,
member role changes and removals, invitations created/revoked/accepted, and platform role
grants.

## 6. Partner-subscription architecture

```mermaid
stateDiagram-v2
    [*] --> APPLIED
    APPLIED --> UNDER_REVIEW
    UNDER_REVIEW --> VERIFIED : staff checks ABN, licences, insurance
    UNDER_REVIEW --> REJECTED
    VERIFIED --> ACTIVE : has an active plan (FREE counts)
    ACTIVE --> SUSPENDED : staff action / compliance
    SUSPENDED --> ACTIVE : staff reinstates
```

Two independent state machines, deliberately separate (paying ≠ verified):

1. **Partner verification status** (`partner_organisation.verification_status`):
   `APPLIED → UNDER_REVIEW → VERIFIED → ACTIVE`, or `SUSPENDED` / `REJECTED`. Changed only by staff, audited.
   Credentials (licence numbers, PI/PL insurance with expiry) are per-category; an expired
   credential removes eligibility for categories that require it.
2. **Partner subscription status** (`partner_subscription.status`), driven **only** by
   verified Stripe webhooks: `TRIALING`, `ACTIVE`, `PAST_DUE`, `CANCELED`, `UNPAID`, `INCOMPLETE`.

**Plans and features are data**: `partner_plan` (`FREE`, `STANDARD`, `PRO`, `ENTERPRISE`
as seed rows, not code), `plan_feature` (feature key + limit, e.g. `lead.monthly_allowance=20`,
`lead.price_discount_bps=2500`, `lead.premium_access=true`, `notifications.priority=true`,
`seats.max=10`), and `price` rows linked to Stripe price IDs. Lead prices live on
`lead_price` (category × value band × plan), editable by admins.

**Entitlement check** (single function, `partners.entitlements.can(partner, action, lead)`),
used by every guarded endpoint and by the matching engine:

```
can_claim(partner, lead):
  partner.verification_status == ACTIVE
  and subscription.status in {ACTIVE, TRIALING}
      or (status == PAST_DUE and now < past_due_since + plan.grace_period)  # if configured
  and plan has feature for lead.tier (premium leads need lead.premium_access)
  and partner holds a current credential for lead.category if category.requires_credential
  and partner has allowance remaining OR credit balance >= lead price
  and lead.release_policy allows another claim (e.g. max 3)
```

On `invoice.payment_failed` → `PAST_DUE`: new premium access stops after the grace
period, history is preserved, billing portal remains reachable. Webhooks are verified
(signature + timestamp), stored idempotently in `stripe_event` (unique event ID), and
processed by the worker. The frontend never decides payment state.

Billing ledger: `credit_ledger_entry` (append-only; purchases, promotional credits, lead
charges, refunds) with a materialised balance; lead fees are recorded at claim time in
the same DB transaction as the claim.

## 7. Lead-matching architecture

```mermaid
sequenceDiagram
    actor C as Customer
    participant API
    participant M as Matching service
    participant W as Worker
    actor P as Partner
    C->>API: Request quotes (project, categories)
    API->>C: Consent screen (consent text vN, categories, max providers, fields to release)
    C->>API: Explicit consent
    API->>API: Store ReferralConsent, create Lead (status AVAILABLE), audit
    API->>W: enqueue match(lead)
    W->>M: candidates = hard filters
    M->>M: score + rank (explainable)
    W->>API: create LeadMatch rows (status MATCHED), notify partners
    P->>API: View lead (anonymised projection only) → VIEWED
    P->>API: Claim
    API->>API: lock lead row, entitlement check, claim count < max, charge fee
    API->>API: LeadClaim + release consented fields, audit "contact.released"
    API->>P: Customer contact details
    P->>API: CONTACTED → QUOTED → WON / LOST
```

**Stage 1 — hard filters (eligibility, never bought):** category served; service area
contains the project location (postcode list, LGA, or radius from office point, stored
as `partner_service_area`); verification ACTIVE; required credentials current; entitlement
allows this lead tier; capacity (`max_open_leads`, paused flag); lead preferences
(project types, min/max value band, timing); not previously declined/excluded by the customer.

**Stage 2 — ranking (explainable, recorded on `lead_match.score_breakdown` JSONB):**
geographic fit, category specificity, credentials, availability, response rate and median
response time, historic customer outcomes (ratings, win rate where customer confirmed),
and plan-feature eligibility (e.g. PRO gets earlier notification window). Payment is a
bounded signal, never the sole or dominant one; any paid placement is flagged
`is_promoted=true` and shown to the customer as "Sponsored".

**Release rules** (`lead_release_policy`, per category/vertical): max providers (default 3),
exclusivity window, claim expiry, auto-expire after N days, fields releasable. The
anonymised projection (`LeadPublicView`) is a separate Pydantic schema built from
whitelisted fields, so PII cannot leak via a forgotten column. Contact details are only
returned from the claim endpoint and only for fields listed in the consent.

**Concurrency:** claim uses `SELECT … FOR UPDATE` on the lead row; claim count, fee charge,
status change and audit event commit in one transaction. Unique constraint
`(lead_id, partner_organisation_id)` on `lead_claim`.

Lead statuses (per match, since one lead goes to several partners): `AVAILABLE` (lead
only), `MATCHED`, `VIEWED`, `CLAIMED`, `CONTACTED`, `QUOTED`, `WON`, `LOST`, `EXPIRED`,
`DECLINED`. Every transition is a `lead_status_event` row and an audit event.

Partner analytics are computed per partner only (own leads, spend, conversion, response
time, category and geography performance). No competitor data, no market-wide figures
unless aggregated across ≥ k partners (k-anonymity threshold, default 5).

## 8. Rules engine (condition AST and evaluator built in Milestone 3; rules in Milestone 4)

* Condition AST in JSONB, validated by a Pydantic discriminated union:
  `{"all": [...]}`, `{"any": [...]}`, `{"not": {...}}`, and leaf
  `{"fact": "property.lot_size_m2", "op": "greater_equal", "value": 600}`.
* Operators: `equals, not_equals, greater_than, less_than, greater_equal, less_equal,
  contains, not_contains, in, not_in, exists, missing`, combined with `all`/`any`/`not`.
  Implemented as a dispatch table of pure functions (`app/modules/conditions`). No `eval`,
  no expression strings. Depth and size are capped (8 levels, 100 nodes).
* The same AST drives questionnaire branching (`visible_when`). The browser has a TypeScript
  mirror for instant show/hide (`apps/web/src/lib/conditions.ts`); both run the shared vectors
  in `tests/fixtures/condition_vectors.json`, and the API re-evaluates on every save.
* Three-valued logic: a leaf on a missing fact yields `UNKNOWN`, which propagates
  (`all` with an unknown and no false → unknown). This is what turns missing
  information into `UNKNOWN` / `NEEDS_INFORMATION` instead of a false negative.
* `RuleVersion` is immutable once `PUBLISHED`; edits create a new version. An assessment
  stores `rule_version_id` for every finding plus a hash of the input facts, making
  results reproducible.
* Confidence is derived, never typed in: a finding starts at the rule version's
  `max_confidence` and is lowered by its sources on the assessment date. `VERIFIED` needs
  every basis source verified, in force and within its review date, against an unchanged
  snapshot; unverified sources give `LIKELY`; disputed, superseded, out-of-force, overdue or
  changed sources give `REVIEW_REQUIRED`; an `UNKNOWN` result gives `UNKNOWN`. Supporting and
  exception sources can lower a finding but never raise it above `LIKELY`. Overall confidence is
  the lowest finding's.

## 9. AI layer (design; built in Milestone 12)

`AIProvider` protocol: `generate_structured(schema, prompt)`, `generate_text`,
`extract_document`, `summarise`, `classify`. Providers selected per task from
configuration (env + admin settings). Every call logged to `ai_provider_log`
(provider, model, task, project, prompt version, schema version, tokens, cost, status,
error). Uploaded content is passed inside delimited, labelled data blocks; the model has
no tools that change permissions, rules or settings; outputs are Pydantic-validated and
post-checked against the findings they are meant to explain.

## 10. Deployment topology

Single Kamatera Ubuntu LTS host running `docker-compose.prod.yml`. Only Caddy publishes
ports 80/443; `db` and `redis` sit on an internal Docker network with no published ports
and the host firewall (UFW + Kamatera firewall) allows only 22 (restricted), 80, 443.
Migration path: point `DATABASE_URL` at a managed/separate Postgres, run `worker` on a
second host against the same Redis, switch `STORAGE_BACKEND=s3`, put Cloudflare CDN in
front of static assets, and run multiple `web`/`api` replicas behind Caddy — all
configuration changes, no code changes. See `docs/DEPLOY_KAMATERA.md`.

## 11. Milestone 1 as built

| Concern | Implementation |
|---|---|
| API | `apps/api`: FastAPI app factory, pydantic-settings config, structured JSON logging, request-ID middleware, security headers, strict CORS, trusted hosts, async SQLAlchemy engine, Redis client. |
| Health | `GET /health/live` (process up), `GET /health/ready` (DB + Redis, 503 if any fails), `GET /version`. |
| Migrations | Alembic configured; baseline migration enables `pgcrypto` and `citext` and creates nothing else. |
| Worker | Celery app (`app.worker`) with `system.ping` task; beat schedule placeholder. |
| Web | `apps/web`: Next.js 16 App Router, TypeScript strict, brand-neutral restrained landing page, `/api/health` route that also probes the API. |
| Packages | `packages/shared-types` (health/version contracts), `packages/ui` (design tokens). |
| Docker | Multi-stage Dockerfiles (non-root users). `docker-compose.yml` (dev), `docker-compose.prod.yml` (Caddy, internal-only DB/Redis, health checks, restart policies). |
| Host allowlist | `ALLOWED_HOSTS` plus always-trusted internal hosts (`127.0.0.1` for Docker health checks, `api` for web→API calls); neither is routable through Caddy. |
| CI | GitHub Actions: ruff, mypy, pytest against Postgres 18 + Redis services; web lint, typecheck, vitest, build; image builds; compose validation. |
| Verified | 42 API/infrastructure tests on Python 3.13 and 3.14, 9 web tests, prod stack smoke test through Caddy. |

## 12. Milestone 2 as built

| Concern | Implementation |
|---|---|
| Modules | `app/modules/identity` (users, credentials, sessions, tokens, emails), `app/modules/tenancy` (organisations, members, invitations, RBAC catalogue), `app/modules/audit` (hash-chained log). |
| Migration | `0002`: 11 tables, role/permission seed (frozen snapshot of `rbac.py`, checked by tests), audit immutability triggers, `member_role` organisation-kind trigger. |
| API | `/v1/auth/*` (register, verify-email, resend, login, logout, logout-all, session, switch organisation, password reset request/confirm, change password), `/v1/organisations/*` (create, read, update, members, roles, invitations, audit events), `/v1/invitations/accept`, `/v1/admin/audit/verify`. |
| Web | BFF proxy `/api/v1/*`, pages `/login`, `/register`, `/verify-email`, `/forgot-password`, `/reset-password`, `/invitations/accept`, `/account`. Per-request nonce CSP (`'strict-dynamic'`, no `'unsafe-inline'` scripts) on these pages via `src/proxy.ts`; statically generated public pages keep the baseline policy. |
| Types | `packages/shared-types/src/api.ts` generated from the API's OpenAPI schema (`npm run generate:types`); CI fails if the schema or types are stale. |
| Dev email | Mailpit in `docker-compose.yml` (UI `http://localhost:8025`). |
| Ops | `python -m app.cli grant-platform-role --email … --role SUPERADMIN`, `python -m app.cli verify-audit`. |
| Verified | 106 API/infrastructure tests (auth flows, throttling, rotation/expiry, CSRF/origin, tenant isolation as an outsider on every org route, privilege rules, append-only and tamper detection, RBAC seed), web unit tests, manual end-to-end run through the Next.js proxy. |

## 13. Milestone 3 as built

| Concern | Implementation |
|---|---|
| Modules | `app/modules/entities` (address, property + ownership, vessel, business profile), `app/modules/projects` (project, status history, task, reminder), `app/modules/conditions` (condition AST + three-valued evaluator), `app/modules/questionnaires` (definitions, versioning, engine, submissions). |
| Migration | `0003`: 16 tables, application DB role grants, RLS on every tenant table, composite tenant foreign keys, triggers that make published questionnaire versions immutable (even for the owner). |
| Database roles | See §3.1. `python -m app.cli provision-db-role` creates or updates the login role from `DATABASE_URL`; the `migrate` service runs it after `alembic upgrade head`. |
| Questionnaires | Reviewed JSON definitions in `app/modules/questionnaires/definitions/` (one per vertical, `<vertical>.general`), synced by `python -m app.cli questionnaires sync` on every migrate. An unchanged definition is a no-op (content hash); a changed one becomes a new published version and retires the previous one. Submissions stay pinned to the version they started on. A question's key is also its fact path; address and object answers expose `key.field` facts. `visible_when` may only reference earlier questions. Hidden answers are pruned on save; validation is all-or-nothing with per-question messages; submit requires every visible required question. The definitions only collect facts: none of them states or implies an approval outcome. |
| Projects | Reference codes (`PLN-`, `VSL-`, `BUS-`, `GRT-`, `SEL-`, `RNT-` + 6 Crockford base32 characters). Users can move between `DRAFT`, `IN_PROGRESS`, `COMPLETED` and `ARCHIVED`; `ASSESSED` and `IN_REVIEW` are reserved for the system (Milestones 4 and 7). Every change is recorded in `project_status_event` and the audit log. Starting a questionnaire moves a draft project to in progress. Delete is soft. |
| Reminders | Stored with recurrence and recipient (must be a member). Delivery is not built yet and the UI says so; see TODO. |
| API | `/v1/organisations/{id}/projects` (+ `/status`, `/status-events`, `/tasks`, `/reminders`, `/submissions`), `/v1/organisations/{id}/submissions/{id}` (+ `/answers`, `/submit`, `/reopen`), `/v1/organisations/{id}/properties`, `/vessels`, `/business-profiles`, `/v1/questionnaires[/{key}]`. |
| Web | App shell with an active-organisation switcher; `/projects`, `/projects/new`, `/projects/[id]` (status, questionnaire, tasks, reminders), `/projects/[id]/questionnaire` (section by section, instant branching, save per section, API errors shown per question, review and submit, reopen), `/account` (organisations, add a business) and `/account/organisations/[id]` (members, roles, invitations, leave). All on the nonce CSP. |
| Verified | 285 API tests (branching, every operator, validation of every question type, versioning and immutability, RLS on every tenant table and the privilege map, cross-tenant writes and references refused by the database, 404s for outsiders on every new route), 11 infrastructure tests, 126 web tests (including the shared condition vectors), and a browser run against a live API: register, create a project, add a task, answer with branching, a server-side validation error, review, submit, add a business and invite a member. |

## 14. Milestone 4 as built

| Concern | Implementation |
|---|---|
| Modules | `app/modules/regulatory` (source organisations, documents, snapshots, references, review events), `app/modules/rules` (rule sets, rules, versions, outcomes, sources, test cases, fact dependencies; `engine.py` is pure and has no database access), `app/modules/assessments` (assessment, finding). |
| Migration | `0004`: 14 tables. Sources and rules are platform tables (no `organisation_id`, no RLS); the application role gets select/insert/update on them, full CRUD only on draft rule-version parts, and select/insert only on `source_snapshot`, `source_review_event`, `assessment` and `assessment_finding`. Assessments are tenant tables with `ENABLE`/`FORCE` RLS and composite tenant foreign keys to project and submission. Triggers make a rule version and its outcomes, sources, test cases and fact dependencies immutable once it leaves `DRAFT` (published → retired is the only allowed change), even for the owner. Seeds `source.manage` and `rule.author` for platform staff, admins and superadmins. |
| Access | Admin routes (`/v1/admin/source-*`, `/v1/admin/rule-*`, `/v1/admin/rules/*`) use platform permissions, which only count while the platform organisation is the active one. Verifying references needs `source.verify`; publishing and retiring need `rule.publish`. |
| Sources | Captured by hand with provenance (official URL, type, jurisdiction code such as `QLD` or `LGA:QLD_CAIRNS`, version label, in-force dates, licence). Snapshots store the pasted text with its SHA-256; an identical capture is a no-op. A reference is verified against the latest snapshot and gets a next review date (a year by default). Editing a reference sets it back to unverified; a new snapshot, an overdue review or the document leaving force puts it in the review queue. Every transition is an append-only review event and an audit event. |
| Rules | A rule set has a vertical, jurisdiction and optional `applies_when` condition (out of scope skips it; unknown scope asks for the missing facts). Each rule has one draft at a time; publishing runs the gate and retires the previous published version. The assessment uses the version published and in force on the assessment date. Warnings (allowed, shown before publishing): unverified sources, facts no questionnaire collects. |
| Assessments | `POST /v1/organisations/{id}/projects/{id}/assessments` runs on the latest submitted answers (409 if none or the project is archived), stores the facts snapshot and hash, engine version, rule sets and scope, and one finding per applicable rule with outcome, confidence and reasons, trace, missing facts and source citations. The assessment date is today in Australia/Brisbane time. A project moves to `ASSESSED`. Replaying stored facts against the pinned versions gives the same findings (tested). |
| Web | `/projects/[id]` has an Assessment panel; `/projects/[id]/assessments/[id]` shows the report (disclaimer, overall confidence, findings grouped by what to do, missing information, "why we say this" from the trace, sources). `/admin` (review queue), `/admin/sources[/id]`, `/admin/rules[/id]`, `/admin/rules/versions/[id]` (draft editor with JSON condition, outcomes per result, source picker, test cases, checks, try-it). All on the nonce CSP. |
| Not built | Requirement tables and tasks from findings (Milestone 5), review reminders (Milestone 11), questionnaire authoring UI and automatic source fetching (backlog). No real regulatory content is shipped: tests use example.com sources and a "Test Council". |
| Verified | 397 API and infrastructure tests, 141 web tests, lint, types and the production build. |

## 15. Milestone 5 as built

| Concern | Implementation |
|---|---|
| Migration | `0005`: `rule_outcome.payload` and `assessment_finding.payload` (jsonb), `rule_set.limitations` (jsonb list), a `(organisation_id, id)` key on findings, tenant tables `approval_requirement` and `evidence_requirement` (forced RLS, composite tenant keys, select/insert only) and `task.finding_id` (only on `RULE` tasks). |
| Outcome payloads | `app/modules/rules/payload.py` validates an outcome's optional payload when a draft is saved: `approval` (kind, authority, pathway, certainty), up to 10 `evidence` items, up to 5 `referral_categories` and a `task`. Certainty defaults from the outcome type and can only be lowered (`APPROVAL_REQUIRED` → `REQUIRED`, `APPROVAL_LIKELY` → `LIKELY_REQUIRED`). Payloads are part of the content hash and immutable once published. |
| Requirements and tasks | Running an assessment copies each matched outcome's payload onto its finding and derives approval and evidence requirements (with the finding's confidence) and rule tasks. A rule task is skipped when an open task with the same title exists, so re-running does not duplicate. The report lists approvals, evidence, referral categories ("who can help"), cited sources and the rule sets' limitations. |
| Content packs | `app/modules/rules/packs/*.json`, loaded with `python -m app.cli rules load-pack <name> --email <staff> [--publish]`. Loading goes through the normal services (audited under that person), never changes existing rows, creates references unverified and rules as drafts unless `--publish`. `planning_qld_cairns`: 3 rule sets (secondary dwelling, subdivision, hillslopes), 9 rules and 9 references summarised from council's CairnsPlan 2016 fact sheets (October 2021) and the Planning Regulation 2017. Every extract is marked as a summary to be replaced with the exact wording when verified. |
| Property facts | `app/modules/property_facts`: a `PropertyFactsProvider` protocol with `none` (default) and a development-only `mock` (refused in production, answers only for the made-up suburb "Mockville"). `GET /v1/organisations/{id}/submissions/{id}/prefill` suggests answers from the linked property (address, lot and plan, land area) and the provider, only for unanswered questions; the customer accepts them. |
| Web | Property picker ("Site") on planning, sell and rent projects; prefill banner in the questionnaire; requirements, who can help, sources and limitations panels in the report; payload editor per outcome and limitations editor in `/admin/rules`. Public `/guides` and two Cairns guides, statically generated, sources listed, `noindex` until verified. |
| Not built | Real property data providers; verified Cairns sources; Part 5 tables of assessment and all Part 9 lot sizes; overlays other than steep land; vessel and business pickers; `sitemap.xml`. |

## 16. Milestone 6 as built

| Concern | Implementation |
|---|---|
| Migration | `0006`: tenant tables `uploaded_document` (soft delete), `evidence` and `generated_document` (forced RLS, composite tenant keys); global `document_template` / `document_template_version` (read-only for the app role, published versions immutable by trigger); a `(organisation_id, id)` key on `evidence_requirement`; `pending_document_jobs(interval)`, a `SECURITY DEFINER` function that returns only the ids of stalled scans and reports. |
| Storage | `app/modules/documents/storage.py`: an `ObjectStorage` protocol with `local` (default: the `uploads` volume at `/data/uploads`, atomic 0600 writes, keys checked against a strict pattern) and `s3` (boto3, server-side encryption, presigned `GET` for `STORAGE_SIGNED_URL_SECONDS`, attachment disposition). Keys are `uploads/<org>/<id>`, `quarantine/<org>/<id>` and `generated/<org>/<id>`. |
| Upload pipeline | `POST /v1/organisations/{id}/projects/{id}/documents` (multipart). Size limit at Caddy (25 MB) and the API (`UPLOAD_MAX_MB`, default 20), per-project file count and per-user hourly rate limits. Type from magic bytes (PDF, PNG, JPEG, WebP, HEIC, DOCX, XLSX, text, CSV), which must agree with the extension; Office files are checked as zips (entry count, uncompressed size and ratio, encryption, macros) without parsing their XML. Filenames are cleaned. |
| Virus scanning | `scanner.py`: `clamav` (clamd `INSTREAM` over TCP to the `clamav` Compose service) or `eicar` (development and tests only, refused in production). A Celery job scans each upload; the sha256 is re-checked first. Infected files move to `quarantine/` and are never served; scanner outages retry with backoff (12 tries) and then mark the file `ERROR`. A beat task re-queues jobs stalled for over 2 hours. Files are unusable (download, evidence, FILE answers) until `CLEAN`. |
| Downloads | Always `Content-Disposition: attachment`, `Content-Security-Policy: default-src 'none'; sandbox`, `nosniff`, `private, no-store`; with S3, a 303 to a short-lived signed URL. Downloads are audited. |
| FILE answers | A FILE answer is a list of upload ids from the same project (`validation.max_files`, default 5). Saving rejects removed, blocked or unchecked files; submitting waits until every file is `CLEAN`. `planning.general` v2 adds an optional "plans, a survey or photos" question. |
| Evidence | `evidence` links a clean upload to an `evidence_requirement` from an assessment; withdrawing removes the link. The report lists what has been provided. |
| Templates and reports | Templates are reviewed files in `app/modules/documents/templates/` synced on migrate (`python -m app.cli documents sync-templates`), a new immutable version when the content hash changes. The body is sandboxed Jinja (autoescape, strict undefined) placed in a system frame that always carries the required sections: metadata (date, project reference, status, template and rules engine versions), review status, assumptions (the answers used), missing information, sources, limitations and disclaimer; rendering fails if any is missing. PDF via WeasyPrint (no network or file fetching), DOCX via python-docx, HTML as a standalone file. Generated in a Celery job, `POST /v1/organisations/{id}/assessments/{id}/documents` returns 202 and the client polls. |
| Web | Documents panel on every project, a file picker for FILE questions, "Your evidence" and "Download this report" on the assessment page. |
| Not built | `RELEASED_TO_PARTNER` sharing waits for partner accounts (Milestone 14; `SHARED_WITH_REVIEWER` arrived in Milestone 7); templates for other verticals arrive with them; per-file thumbnails and previews. |

## 17. Milestone 7 as built

| Concern | Implementation |
|---|---|
| Migration | `0007`: platform tables `professional` (one profile per user and practice), `professional_credential` and `professional_service`; tenant tables `review_request`, `review_comment`, `finding_override` and `review_decision` (forced RLS; comments, overrides and decisions are append-only for the app role). A partial unique index allows one open review per project. Two `SECURITY DEFINER` functions return only ids: `review_request_organisation(id)` (the customer organisation of a review, so a reviewer's request can bind that tenant before the row is read) and `review_queue(professional, statuses)`. New platform permissions `professional.verify` and `review.assign` for staff. |
| Professionals | A member with `review.perform` in a `PROFESSIONAL_PRACTICE` organisation creates a profile at `/review/profile`, lists credentials and the verticals they review. Staff check each credential against the issuer's register (`/admin/professionals`) and activate the profile; activation needs a current checked credential, at least one service and the practice role. Nobody can check their own credentials or activate themselves. |
| Workflow | `REVIEW_REQUESTED` → `ASSIGNED` (staff pick an eligible professional, never one from the customer's organisation) → `IN_REVIEW` → `CHANGES_REQUIRED` ⇄ `IN_REVIEW` (the customer resubmits, optionally with a newer assessment) → `APPROVED` or `COMPLETED`; `CANCELLED` by the customer while open; the reviewer can decline before starting. Only the project's latest assessment can be sent. The project shows `IN_REVIEW` while a review is open. Every step is audited in the customer's organisation; assignment, resubmission and decisions send email with links only. |
| Reviewer access | Every reviewer request resolves the review's organisation, binds it as the tenant and then requires the assignment on the row. The reviewer sees the answers, the assessment, evidence files on that assessment and files the customer marked `SHARED_WITH_REVIEWER` (a toggle in the documents panel). |
| Overrides | A reviewer changes a finding's outcome or confidence with a reason (10+ characters); `VERIFIED` needs a verified source reference. Overrides are append-only, the latest one per finding is current, and the customer sees both the original and the change. Reports apply overrides and show the reviewer, decision date, notes and a table of changes; the report review status is computed at render time. |
| Evidence and tasks | The reviewer accepts or rejects evidence (rejecting needs a note the customer sees) and can add tasks to the project (`TaskSource.REVIEWER`). |
| Not built | Paid reviews (`payment_id`, service prices) wait for Milestone 13; credential evidence uploads; review `DRAFT` status (requests go straight to `REVIEW_REQUESTED`); automatic assignment and due-date reminders. |

## 18. Milestone 8 as built

| Concern | Implementation |
|---|---|
| Migration | `0008`: `marketplace_category`, platform reference data (no tenant, read-only for the app role). No other schema change: the approval map is built from Milestone 5's `approval_requirement.certainty`. |
| Marketplace categories | The shared taxonomy of kinds of professional (`key`, `label`, `description`, `verticals`, `requires_credential`, `restricted`, `active`), a reviewed file `app/modules/marketplace/categories.json` synced on every migrate (`python -m app.cli marketplace sync-categories`). Changed entries update in place; removed ones are deactivated, never deleted, so old findings keep their label. `GET /v1/marketplace/categories[?vertical=]` for signed-in users. Partners join categories in Milestone 14. |
| Rules-driven mapping | An outcome's `referral_categories` must be active marketplace categories: saving a draft refuses unknown keys, and the publish gate refuses categories retired since. Business type → category is ordinary rules (`business.au.who_can_help` maps food, personal appearance, childcare and trade businesses, and every business, to categories, each citing the sources behind the approvals it helps with); approval rules add their own categories (liquor → liquor licensing consultant, fit-out → building certifier, and so on). Reports and the web show the category's label and description. |
| Approval map | `app/modules/assessments/approval_map.py`: every approval kind once, at the strongest certainty any finding gave it (a later "not identified" never hides an earlier "required"), in four columns: Required, Likely required, May apply, Not identified. "Not identified" comes from `NOT_REQUIRED` outcomes that carry an approval, so the map shows what was checked and not found, not just what applies. `AssessmentOut.approval_map`. |
| Content pack | `business_qld_cairns`: 8 rule sets, 20 rules, 14 references from ATO, Ahpra, FSANZ, Queensland Government, Business Queensland, QBCC, WorkSafe Queensland, WorkCover Queensland, Queensland Department of Education and Cairns Regional Council pages read on 2026-10-09: GST and PAYG withholding registration, food business licence and Standard 3.2.2A, liquor licence, WorkCover policy, fit-out building approval, higher risk personal appearance services, QBCC building and plumbing licences, electrical licences, Ahpra registration, education and care approvals, Cairns footpath dining and home based business. Every reference is an unverified summary; rules take effect from the date the source was read and are capped at likely. Load with `python -m app.cli rules load-pack business_qld_cairns --email <staff> [--publish]`. |
| Questionnaire | `business.general` v2 adds the state and council area, expected turnover, and follow-ups by kind of business (personal appearance services, trade work, registered health profession, education and care service, unpackaged food). |
| Business profiles | A Business panel on business and grant projects picks or adds a business profile; the questionnaire prefill suggests ABN, structure, size, turnover, state and address from it. |
| Reports | `BUSINESS_APPROVAL_MAP` template (PDF, DOCX, HTML) with the map, evidence, who can help and findings inside the standard frame. |
| Web | The assessment page shows "Your approval map" for business projects (and in the reviewer workspace), flagging approvals behind a finding a reviewer changed. |
| Not built | Other states' and councils' business rules; signage, trade waste, noise and music licensing; ABN eligibility; checking food licence exemptions item by item; a category picker in the rule editor (unknown keys are refused with a message). |


## 19. Milestone 9 as built

| Concern | Implementation |
|---|---|
| Migration | `0009`: tenant tables `vessel_certificate` (soft delete), `safety_management_system` (one per project), `project_checklist` and `checklist_item`, all with forced RLS and composite tenant keys. The app role can select, insert and update certificates and SMSs, and has full CRUD on checklists (a customer can remove a checklist they added). |
| Modules | `app/modules/vessels` (certificates, the SMS builder and its structure file), `app/modules/checklists` (definitions, adding them to projects, ticking items). |
| Checklists | Reviewed files in `app/modules/checklists/definitions/<key>.json`, each citing its sources. They are not synced to the database: adding one to a project copies its items with the definition's hash, so editing a file never rewrites a list in progress. A rule outcome's payload may name `checklists` (saving a draft refuses unknown keys; the publish gate checks them again); an assessment adds each named checklist once per project (origin `RULE`, linked to the finding), and the customer can add others (`USER`) and remove those. Items are `OPEN`, `DONE` or `NOT_APPLICABLE`; a required item needs a note to be marked not applicable. `GET /v1/checklists[?vertical=]`, `/v1/organisations/{id}/projects/{id}/checklists`, `/checklists/{id}`, `/checklist-items/{id}`. |
| Certificates | `/v1/organisations/{id}/vessels/{id}/certificates` and `/vessel-certificates/{id}`: kind, number, issuer, dates (expiry not before issue), an optional clean upload as the copy. `state` is computed: `EXPIRED`, `EXPIRING` (within 60 days, Queensland date), `CURRENT` or `NO_EXPIRY`. Reminders wait for Milestone 11. |
| SMS builder | `app/modules/vessels/sms_structure.json` lists Marine Order 504 Schedule 1's parts (18 elements in 6 sections, with guidance summarised from the source and which are required). `GET/PUT /v1/organisations/{id}/projects/{id}/sms` (vessel projects only) merges text per element (blank clears it, 20,000 characters each) and reports parts written, the structure hash it was saved against and a starting text for the vessel details part built from the linked vessel. Audit events name the elements changed, never the text. |
| Reports | `POST …/assessments/{id}/documents` takes an optional `template`: vessel projects offer `VESSEL_PATHWAY` (default: approval map, checklists with progress, evidence, who can help, findings) and `SMS` (the customer's text under each heading, parts still to write, the structure's sources; refused while the SMS is empty). `GeneratedDocumentOut.template_key` says which report a file is. Report contexts now include the project's checklists. |
| Content pack | `vessel_au_qld`: rule set `vessel.au.domestic_commercial` (scope: business use) with domestic commercial vessel status, UVI, certificate of survey, non-survey approval (Exemption 02), certificate of operation (Exemption 03), SMS, simplified SMS and master's certificate of competency; `vessel.qld.registration` (scope: based in Queensland) with recreational registration (3 kW or more), the marine driver licence (over 4.5 kW), the PWC licence and a note that Queensland doesn't register commercial vessels. 16 references from AMSA, the Federal Register of Legislation (Marine Order 504, as made), Queensland Government and Maritime Safety Queensland pages read on 2026-10-09, all unverified summaries; rules take effect from that date and are capped at likely. Exemptions are expressed by De Morgan (the condition language has no `not`). |
| Questionnaire | `vessel.general` v2 adds engine power, petrol inboard, overnight hire, the AMSA operational area (optional, so "not sure" stays unknown) and asks every commercial vessel for its passenger count (0 allowed). |
| Marketplace | New categories `naval_architect`, `marine_safety_consultant` and `maritime_trainer`. |
| Web | Vessel panel on vessel projects (pick or add a vessel, its certificates with expiry badges), a Checklists panel on any project with checklists, a link to the SMS builder (`/projects/[id]/sms`, section-by-section save, "start from your vessel's details"), the approval map on vessel assessments (and in the reviewer workspace) and a two-report download panel. |
| Not built | Reading the Exemption 02/03 schedules, Marine Orders 503 and 505 and the National Law itself into rules; survey frequency and crewing numbers; Queensland's smooth and partially smooth water boundaries; other states' recreational registration; certificate expiry reminders (Milestone 11); AMSA form pre-filling. |
