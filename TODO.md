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
- [x] Moved to backlog, built in Milestone 18: generic API-wide rate-limiting middleware

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
- [x] Moved to Milestone 13 (built there): paid reviews (`payment_id`; prices per vertical, not per professional, because staff choose the reviewer)
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
- [ ] Next: verify the pack's references (open points: entry notice period for showing buyers, disclosure timing rules); other states; Form 1 entry condition report and disclosure statement generation; notification preferences (built in Milestone 21)

## Milestone 12 — AI abstraction and drafting ✅
- [x] `AIProvider` protocol (`generate_structured`, `generate_text`); providers `none` (default), `mock` (refused in production) and `anthropic` (official SDK, JSON structured output, refusal fallback), chosen by `AI_PROVIDER`
- [x] Prompt registry: reviewed prompt files synced on migrate into immutable `prompt_version` rows
- [x] Pydantic output validation (versioned schemas), finding-reference post-check, and a grounding check that rejects numbers and links not in the input
- [x] `ai_job` and append-only `ai_provider_log` (tokens, cost, latency, outcome); worker job with retries and the stalled-job sweep; per-user hourly limit; identical input reuses the draft
- [x] Plain-language explanation of an assessment's findings and grant application notes, shown as "AI draft" panels; staff usage and prompts at `/admin/ai`
- [ ] Next: AI text in generated reports (`generated_document.ai_job_id`), document extraction from uploads (with the S3 safeguards), per-task model choice, an evaluation set for the prompts

## Milestone 13 — Customer payments ✅
- [x] Products, features and plan limits from a reviewed catalogue file (synced on migrate); prices set by staff at `/admin/billing` (immutable, replaced not edited)
- [x] Stripe Checkout (one-off and subscription) and the customer portal; one Stripe customer per organisation
- [x] Webhooks: signature and timestamp verified, stored once per event id, applied by the worker (out-of-order safe, retried, staff retry)
- [x] Entitlements: plan limits with a 7-day past-due grace; RentReady free accounts manage 1 rental, Manage 10, Manage Plus unlimited (enforced only while a plan is on sale)
- [x] Paid professional reviews (moved from Milestone 7): `PAYMENT_PENDING` until Stripe confirms, then staff assign
- [x] Customer billing page (plan, usage, payments, invoices) and staff billing page (prices, webhook events)
- [x] Built in Milestone 22: automatic refunds when a paid review is cancelled before work starts
- [ ] Next: plan switching in the app; coupons and trials; one-off purchases of reports

## Milestone 14 — Partner accounts, subscriptions, dashboard ✅
- [x] Partner application + staff verification, categories, service areas, credentials (`VERIFIED` folded into `ACTIVE`; see ARCHITECTURE §6)
- [x] Plans/features (data), Stripe partner subscriptions, PAST_DUE grace logic: partner plans are `PARTNER_PLAN` catalogue products on the Milestone 13 billing; categories and areas are soft limits, members a hard limit. Limit numbers are first guesses for Jules to confirm
- [x] Partner portal surface on `partners.` host (`/partner`, any host; `partners.` redirects `/` there)
- [ ] Next: `RADIUS` service areas; credential evidence uploads; public provider profile; automated ABN and licence register checks; credential expiry reminders

## Milestone 15 — Lead engine ✅
- [x] Referral consent (versioned text, fields released)
- [x] Matching (hard filters + explainable ranking), release policy, claiming with row locks
- [x] Contact locking/release, lead fees + credits ledger, outcomes
- [x] Partner E2E test (16 steps, API level) + negative cases
- [ ] Next: confirm the placeholder numbers (included referrals 3/15/50 a month, 14-day expiry, waves of 5 then 3 a day), set lead fees and a credit pack price; per-category lead preferences; quotes (built in Milestone 23); sponsored placement; claw back credit when a credit-pack payment is refunded

## Milestone 16 — Marketplace analytics ✅
- [x] Per-partner analytics: own referrals as a funnel (offered, accepted, declined, missed, quoted, won, lost), reply times, fees, by category, area and month (`/partner/analytics`)
- [x] k-anonymous benchmarks: other partners' medians (accept rate, win rate, reply time) only when at least `ANALYTICS_MIN_PARTNERS` (default 5) other partners contribute; nothing names or counts them
- [x] Staff marketplace figures (`/admin/analytics`): requests, supply gaps (no partner available), time to first acceptance, outcomes and fees by category, area, month and partner
- [ ] Next: CSV export; charts; area benchmarks once there are enough partners per region

## Milestone 17 — Production hardening ✅
- [x] Backups: nightly `pg_dump` and uploads archive by the `backup` service (14 days on the server), off-site copies to S3-compatible storage by the worker (`BACKUP_S3_*`), weekly automatic restore checks into a scratch database, and a tested restore command
- [x] Monitoring and alerting: scheduler heartbeat, queue, backup, restore-check, off-site and disk checks every 10 minutes, alerts to platform admins and `OPS_ALERT_EMAILS`, `/health/jobs` for an external uptime monitor, `/admin/ops`, error tracking with `SENTRY_DSN`
- [x] Security testing: OWASP ZAP baseline scan and dependency audits (pip-audit, npm audit) in CI; hash-based CSP for static pages; forms post (a ZAP finding)
- [x] Kamatera go-live (approvalready.au, 2026-10-10)
- [x] Browser (Playwright) end-to-end tests: the partner journey from Milestone 15, and a CSP check
- [ ] Next: choose the backup bucket (see backlog: object storage vendor) and set `BACKUP_S3_*`; set `OPS_ALERT_EMAILS` and an external uptime monitor; WAL archiving for point-in-time recovery once a day's loss matters; more browser journeys (customer questionnaire, professional review, billing)

## Milestone 18 — Account security ✅
- [x] Two-step sign-in with an authenticator app (TOTP) and single-use recovery codes; set up, turn off and new codes from Account; secrets encrypted at rest
- [x] Required for platform staff before staff pages and routes work (`STAFF_MFA_REQUIRED`); operator reset `python -m app.cli auth reset-mfa`
- [x] Breached-password check (Have I Been Pwned range API, k-anonymity, fail open) at registration, reset and change (moved from backlog)
- [x] Per-IP rate limits on every API route (moved from backlog)
- [x] Change password on the account page
- [ ] Next: passkeys and Google/Microsoft sign-in; optional "require two-step sign-in" for business and partner organisations; per-user API limits

## Milestone 19 — Legal and privacy basics ✅
- [x] Terms of Use, Privacy Policy and contact pages; footer links on every page
- [x] Agreement recorded at registration (versioned); signed-in users asked to agree to new versions
- [x] Download my data (account and personal workspace as JSON) and close my account from Account
- [x] Privacy requests from the contact page, worked by staff at `/admin/privacy` within 30 days; operations check and alerts
- [x] `sitemap.xml` and `robots.txt` (moved from Milestone 5's backlog note)
- [ ] Next: have a lawyer review the Terms and Privacy Policy and add the operating entity's legal name and ABN (`apps/web/src/lib/legal.ts`); ~~automatic deletion of a closed account's workspace after the 30 days~~ (Milestone 29); closing business organisations; ~~change of email address~~ (Milestone 28)

## Milestone 20 — Reliable email delivery ✅
- [x] Email outbox: every email is queued (sealed, erased once sent) and sent by the worker, so a slow or failing mail server no longer slows or loses sign-up, reset, invitation, review and referral emails
- [x] Retries with back-off for about ten hours; refused addresses fail at once; a sweep every minute catches anything missed and removes rows after 30 days
- [x] Ops check "Email delivery" on `/admin/ops` and in the watchdog's alerts
- [ ] Next: bounce and complaint handling from the mail provider; a staff view of failed emails per address; ~~notification email preferences and unsubscribe links~~ (Milestone 21)

## Milestone 21 — Email and notification settings ✅
- [x] Per-person choice for reminders, grant rounds, referrals and (staff) source reviews: email and in the app, in the app only, or off; applies in every organisation (Account > Email and notifications)
- [x] Unsubscribe link in every reminder and alert email, plus `List-Unsubscribe` one-click headers (RFC 8058) for Gmail and Outlook; no sign-in needed, the link only switches emails off
- [x] Account emails (sign-in, password, security, invitations, reviews) and ops alerts stay always on
- [ ] Next: a per-project mute; digest emails (one a day instead of each reminder); SMS

## Milestone 22 — Refunds for paid reviews ✅
- [x] Cancelling a paid review before a reviewer starts refunds it in full through Stripe; the customer is told before cancelling and emailed when it is on its way
- [x] A payment that arrives after the review was cancelled is refunded in full
- [x] Staff (`billing.refund`) refund part or all of a review with a reason, e.g. after work started; failed refunds alert staff
- [x] `refund` table (migration 0021): recorded before sending, idempotent retries, worker sweep for refunds left pending
- [ ] Next: refunds for other one-off products once any are sold; claw back lead credit when a credit-pack payment is refunded (Milestone 15 next)

## Milestone 23 — Quotes ✅
- [x] Partners who accepted a referral send the customer a written quote: line items, GST, valid until, start estimate, terms; revisions supersede the waiting quote (migration 0022, `lead_quote`, fixed once sent by a trigger)
- [x] Customers compare quotes per job on `/projects/[id]/referrals`, accept one (optionally declining the others) or decline with a note; referrals move to won or lost
- [x] In-app and email notifications both ways; audit events; analytics unchanged (status events)
- [ ] Next: PDF quotes; reminders before a quote expires; quote templates per partner; ~~messages between customer and partner~~ (Milestone 26)

## Backlog / decisions to revisit
- [ ] Questionnaire authoring in the admin UI (definitions are reviewed JSON files in the repo; revisit when non-developers need to edit them)
- [ ] Fetch source documents automatically for snapshots (manual capture only for now; no claims of live integration)
- [x] Generic per-IP rate limiting for all API routes (Milestone 18; per-user limits still open)
- [x] Breached-password check (HIBP k-anonymity range API) at registration and reset (Milestone 18)
- [~] MFA (TOTP) built in Milestone 18; passkeys via `auth_identity` and Google/Microsoft OIDC still open
- [x] Send transactional email from the worker (outbox) instead of in-request (Milestone 20)
## Milestone 24 — Automatic source checks ✅
- [x] "Check the official page now" on each source document: the app reads the official address and saves a snapshot when the wording changes (marked "read by the app"), or says why it couldn't
- [x] Weekly check (Mondays 6 am Brisbane) of every source document that is in force, not superseded and set to "Check every week"; one notification and email to source staff listing what changed and what couldn't be read
- [x] Safe fetching: https only, allowed domains (`SOURCE_FETCH_ALLOWED_DOMAINS`, government by default), public addresses only, every redirect re-checked, size and time limits
- [x] Page text keeps the wording only (main content, no scripts, menus, headers or footers) so banners and scripts don't count as changes; PDFs are compared by their bytes and flagged for pasting by hand
- [x] `source_check` history (append-only), `python -m app.cli sources check` to run it at once
- [ ] Next: read PDF text (needs a PDF library); show a word-level diff between snapshots; per-document check frequency; a public "last checked" date on guide pages

## Milestone 26 — Messages between customers and partners ✅
- [x] One conversation per referral a partner accepted: the customer writes from `/projects/[id]/referrals`, the partner from `/partner/leads/[match]`
- [x] Open while the job is in progress or won, read-only once lost; up to 30 messages an hour from each side
- [x] Unread counts, "Seen", and a notice (in the app and by email, per the Referrals setting) for the first message waiting
- [x] `lead_message` (migration 0025): never edited or deleted (trigger); the text stays out of the audit log
- [ ] Next: attachments (reusing the scanned upload pipeline); include messages in "Download my data"; reminders before a quote expires; PDF quotes

## Milestone 27 — Staff accounts page ✅
- [x] `/admin/accounts`: find any account by email, name, business name, ABN or id (posted, so emails stay out of logs), with filters for active, unconfirmed, suspended, staff and closed accounts
- [x] Account page: organisations and roles, two-step sign-in and recovery codes, password age, signed-in devices, and recent history including what staff did to it
- [x] Support actions for platform administrators (`platform.users.manage`, migration 0026): resend the verification email, send a password reset link, sign out everywhere, reset two-step sign-in (no server command needed), suspend and restore; reasons kept in the audit log
- [x] Safeguards: no actions on your own account, only a super administrator can change a staff member's account, closed accounts are read-only, every view and action audited
- [ ] Next: change staff roles from the page; suspend a business organisation; staff notes on an account

## Milestone 25 — TradeReady: importing and exporting goods ✅
- [x] `TRADE` vertical (migration 0027), `trade.general` questionnaire, business profile prefill
- [~] Content pack `trade_au` (4 rule sets, 21 rules, 16 references): import declarations, ICS registration, GST and deferred GST, biosecurity permits, imported food inspection, stink bug season, vehicles, AICIS, ARTG, refrigerant equipment, EESS, firearms, tobacco, wildlife, export declarations, prescribed goods, Defence export permits. Every reference is an **unverified summary**: capture and verify in `/admin/sources`
- [x] Marketplace categories for import and logistics companies: customs brokers, freight forwarders, logistics and warehousing providers, import and export compliance consultants; `review.trade` product
- [x] Import and export approval map report; guides for importing and exporting
- [ ] Next: tariff classification help; BICON look-up links per commodity; MICoR for exports; freight quote requests through the existing quotes feature

## Milestone 28 — Change of email address ✅
- [x] Account, Security: ask for a new address with the password (and a two-step code when on); a link goes to the new address, a notice to the old one, and nothing changes until the link is opened
- [x] Confirming moves the account, marks the address confirmed, cancels links still waiting in the old inbox and tells the old address; a waiting change can be cancelled
- [x] No account enumeration: an address another account uses gets the same answer, and that inbox is told instead of sent a link
- [x] Migration 0028: `one_time_token.new_email`, purpose `EMAIL_CHANGE`
- [ ] Next: update the Stripe customer's email for receipts; staff changing a customer's address from Admin > Accounts

## Milestone 29 — Deleting closed accounts' workspaces ✅
- [x] A closed account's personal workspace (projects, answers, files, reports) is deleted automatically 7 days after closing (`PRIVACY_PURGE_AFTER_DAYS`), well inside the Privacy Policy's 30 days; payment records and the security log are kept
- [x] Staff see when each will be deleted at `/admin/privacy`, can delete one now, or keep it by declining the request with a reason
- [x] Closing withdraws referrals still offered to partners; partners keep the referrals they accepted (detached from the deleted project) but can't message or quote a closed account
- [x] Database function `purge_closed_workspace` (migration 0029) only empties closed personal workspaces and never payment tables; a test makes every new workspace table a deliberate delete-or-keep choice
- [ ] Next: closing business organisations; a lawyer's check that the kept records match what the law requires

## Backlog / decisions to revisit
- [ ] Questionnaire authoring in the admin UI (definitions are reviewed JSON files in the repo; revisit when non-developers need to edit them)
- [x] Fetch source documents automatically for snapshots (built in Milestone 24; PDFs still pasted by hand)
- [ ] Generic per-user/per-IP rate limiting for all API routes (auth routes already limited)
- [ ] Breached-password check (HIBP k-anonymity range API) at registration and reset
- [ ] MFA (TOTP) and passkeys via `auth_identity`; Google/Microsoft OIDC
- [ ] Send transactional email from the worker (outbox) instead of in-request
- [ ] `npm audit` flags `braces` (high) via `eslint-config-next` → `fast-glob`; dev-only lint tooling, not shipped in images. Re-check on next eslint-config-next release
- [ ] Brand/domain tables + Next.js host middleware (not needed until a second brand or partner surface; Milestone 14)
- [ ] Decide object storage vendor (Wasabi / Backblaze B2 / AWS S3 Sydney) — prefer an Australian region
- [ ] Obtain Australian legal advice on advice/referral/licensing boundaries before launch
- [ ] Review `julesbris/council-signon-system` for reusable council-domain assets
