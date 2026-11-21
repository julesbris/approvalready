# RemoteSafe: architecture assessment and Stage 1 plan

RemoteSafe is remote-work journey planning and risk intelligence for councils, utilities,
contractors and other organisations working across regional and remote Australia. It is a
separate module inside ApprovalReady (`apps/api/app/modules/remotesafe`, web pages under
`/remotesafe`) that shares the platform's sign-in, organisations, row-level security,
audit log, report rendering and deployment.

This document is Milestone 1 (repository audit and architecture) and records what
Milestone 2 (journey management MVP) built in the first pull request.

## 1. Repository audit (what exists and what RemoteSafe reuses)

Checked against the code on `main` at Alembic head 0034, not against older documentation.

| Area | What is there | RemoteSafe use |
| --- | --- | --- |
| Backend | FastAPI modular monolith (`apps/api/app/modules/*`), SQLAlchemy 2 async, Pydantic 2, Python 3.14 image | New module `remotesafe` in the same pattern (models, schemas, service, router) |
| Database | PostgreSQL 18, Alembic migrations, UUIDv7 keys, text enums with CHECK constraints | Migration 0035 adds 11 `rs_*` tables; no existing table changes |
| Tenancy and RLS | Every tenant table has forced RLS on `app.current_org`; composite tenant foreign keys; app connects as a non-owner role; `tests/test_rls.py` holds the reviewed privilege map | All `rs_*` tables are tenant tables with forced RLS, composite FKs and explicit grants (append-only for history tables) |
| Auth and roles | Opaque session cookies, CSRF, two-step sign-in for staff, DB-driven role/permission catalogue per organisation kind | Organisation membership (`org.read`) gates every route. RemoteSafe roles live in `rs_member_role`, so the platform role catalogue is untouched |
| Audit | Append-only hash-chained `audit_event` | Approvals, control exceptions, role, policy and tier changes are recorded there, plus a per-journey trail in `rs_journey_event` |
| Web | Next.js 16 app, server pages call the API with the user's cookies, browser calls go through the `/api/v1` proxy with CSRF, nonce CSP for signed-in pages, design tokens in `globals.css` | New pages under `/remotesafe` (added to the nonce CSP list), existing panel/form/card classes, a few rating styles |
| GIS | Address, parcel and overlay lookups for QLD/NSW/VIC/TAS/ACT (`modules/lookups`), no map component, no PostGIS | Not used yet. Stage 1 stores planned places and optional coordinates; maps and spatial data are Milestone 3 |
| Reports | Jinja sandbox + WeasyPrint PDF with ApprovalReady branding (`documents/render.py`) | PDF journey plan reuses the same renderer and brand |
| Jobs and notifications | Celery + Redis, email outbox, notifications, reminders scheduler | Not used yet. Check-in monitoring and escalation (Milestone 4) will build on these |
| Billing | Stripe-based plans for ApprovalReady products | Not used. RemoteSafe has its own tier flag (Starter, Professional, Enterprise) set by staff, no payment |
| Deploy | Docker Compose on one Kamatera server, GitHub Actions CI then automatic deploy on merge to `main` | Nothing new to configure: one migration, no new environment variables or services |

Things found that matter for RemoteSafe:

* There is no PostGIS extension and no map library in the web app. Adding PostGIS changes the
  database image and backups, so it is a Milestone 3 decision, not a Stage 1 one.
* Platform staff can't read tenant rows (RLS). RemoteSafe keeps that: staff can set an
  organisation's tier but can't see its journeys.
* Merging to `main` deploys to production automatically. The RemoteSafe PR is opened but not
  merged.
* The pinned Next.js version has a moderate published advisory (`next build` prints it). It is
  unrelated to RemoteSafe and should be upgraded in its own PR.

## 2. Architecture decisions

1. **Separate module, shared platform.** RemoteSafe has its own tables, routes and pages and
   never writes to property, planning, finance or report tables. Removing it means dropping
   the module, its migration and its pages.
2. **Business organisations are the tenant.** An organisation administrator turns RemoteSafe on
   for a business organisation; personal workspaces can't. Records are isolated by RLS on
   `organisation_id`, exactly like the rest of ApprovalReady.
3. **Product roles in their own table.** Worker, supervisor, journey monitor and WHS
   administrator are RemoteSafe roles held by members of the organisation. The organisation
   administrator role manages them. Least privilege: a worker sees journeys they plan or are on;
   a supervisor or monitor sees journeys they are assigned to; WHS and organisation
   administrators see all of the organisation's journeys. A journey someone can't see answers
   404, the same as one that doesn't exist.
4. **Transparent rules engine (no prediction).** `library.json` lists 19 hazards and 21 controls.
   Each hazard has a plain rule over the plan, likelihood and consequence on 1 to 5 planning
   scales, controls and a residual likelihood. Each finding lists the evidence and where it came
   from. Ratings choose the approval pathway; they are labelled as policy categories, not
   probabilities.
5. **Stop conditions can't be configured away.** No satellite device on a remote or no-coverage
   route, a confirmed road closure, or missing emergency arrangements (monitor, contacts,
   check-ins) make a journey CRITICAL. Only a WHS administrator can approve it, and only with a
   documented alternative process that is stored with the approval.
6. **Configurable, but only stricter where it matters.** WHS administrators on the Enterprise tier
   can change ratings, bands and assumptions and switch off irrelevant hazards. They can add
   mandatory controls but can't make baseline ones optional, can't remove stop conditions, and
   can't stop a material change from sending an approved journey back for approval.
7. **Revisions and material change.** Submitting snapshots the plan (`rs_journey_revision`). A
   change to route, vehicle, places, people, communications, timing, check-ins or weather on a
   submitted or approved plan starts a new revision and reruns the assessment; an approved plan
   goes back to "waiting for approval" and every completed control is cleared.
8. **Time zones.** Times are stored in UTC. People enter wall-clock times in an Australian zone
   (the leg's own zone, else the journey's), so a Queensland departure and a Broken Hill arrival
   are each right through daylight saving. A wall time skipped by daylight saving is refused.
9. **No invented data.** Stage 1 fetches no external data. Road surface, coverage, crossings,
   closures, remoteness and weather checks are what the planner recorded and the source they
   named, and the assessment says so. Every assessment lists the sources not connected yet.
10. **Honest about monitoring.** Check-ins are planned, not received. The app says on every
    journey, the dashboard and the PDF that missed check-ins are not detected or escalated yet,
    and that RemoteSafe does not replace 000 or the organisation's emergency plan.
11. **Data for future probabilistic models.** Every assessment run is kept with its facts
    (driving hours, night hours, distance, unsealed km, crossings, remoteness, communications,
    occupants), findings and policy version; events record failed controls, exceptions and
    escalations. That is the structured history a later, calibrated model would need. No model is
    built or shown.

## 3. What Stage 1 built

Backend (`apps/api/app/modules/remotesafe`):

* `models.py`: 11 tenant tables (settings, member roles, vehicles, journeys, route legs, planned
  check-ins, risk assessments, hazard findings, control checks, events, revisions).
* `engine.py`, `policy.py`, `library.json`: the rules engine and configurable policy.
* `service.py`: access rules, workflow (Draft, Submitted, Changes requested, Approved, Active,
  Escalated, Completed, Cancelled, then archived), material-change handling, controls and the
  authorised exception process, dashboard.
* `router.py`: `/v1/organisations/{org}/remotesafe/...` (about me, enable, members and roles,
  vehicles, journeys, legs, check-ins, assessment, controls, exceptions, approve and other
  actions, events, revisions, PDF, JSON and CSV export, dashboard, policy) and a staff route to
  set the tier.
* `report.py`: the PDF journey plan (route overview, itinerary, risk assessment, controls,
  communications schedule, emergency contacts, approval record, revision and creation time,
  limitations).
* `entitlements.py`: tiers and feature flags, each marked built or not.

Web (`apps/web`): `/remotesafe` (summary, approval queue, journeys), `/remotesafe/journeys/new`,
`/remotesafe/journeys/{id}` (plan, route legs, check-ins, risk table, checklist, actions,
history, PDF), `/remotesafe/admin` (roles, vehicle register, risk ratings). A RemoteSafe link
shows in the header while a business organisation is active.

Migration: `0035` (after `0034`). New tables only.

## 4. Tests

* `tests/test_remotesafe_engine.py` (25): ratings, stop conditions, night driving in each leg's
  own zone, Queensland vs NSW daylight saving, non-existent local times, check-in gaps, fuel
  range, policy validation.
* `tests/test_remotesafe.py` (15): through the API with real database and RLS: enabling,
  roles, the scenarios below, no self-approval, request changes, planning for others, policy and
  tier, isolation between organisations and between workers, removed members, cross-border legs,
  PDF and JSON export, CSV for administrators, dashboard, vehicle register.
* `tests/test_rls.py`: the reviewed privilege map now includes the 11 tables; the existing test
  checks every tenant table has forced RLS.
* Web: `src/lib/remotesafe.test.ts`, `src/components/remotesafe/RemoteSafe.test.tsx`.

Required scenarios:

| # | Scenario | Status |
| --- | --- | --- |
| 1 | Cooktown to Coen with limited communications | Tested: critical without a satellite device; high with one, needing WHS approval |
| 2 | Route affected by a confirmed road closure | Tested: stop condition with the named source and time; approval only with a documented alternative |
| 3 | Worker misses a scheduled check-in | Not built (Milestone 4). The app states that missed check-ins are not detected |
| 4 | Check-in queued offline, never delivered | Not built (Milestone 5) |
| 5 | Journey modified after approval | Tested: new revision, approval and controls cleared, back to approval |
| 6 | Vehicle fails a mandatory pre-start check | Tested: can't start; worker can't mark it not applicable; only a WHS administrator's exception lets it go |
| 7 | Weather or road service unavailable | No external service is called in Stage 1; the assessment lists the sources not connected. Failure handling is tested when Milestone 3 adds them |

All journey data in tests is simulated and labelled SIMULATED.

## 5. Security and safety limitations (Stage 1)

* RemoteSafe does not receive check-ins, detect missed ones, notify anyone or escalate
  automatically. Do not describe it as monitoring.
* It does not look up roads, closures, weather, flood, coverage, terrain or remoteness.
* Ratings are a planning aid set by policy, not validated risk science.
* No live location is collected; only planned places and optional coordinates.
* Evidence attachments for controls are not built yet (the column is there for Milestone 6).
* No automatic retention or deletion schedule yet for RemoteSafe records beyond the existing
  closed-workspace deletion (which only covers personal workspaces).
* Staff set tiers by hand; there is no payment.

## 6. Remaining milestones

* **Milestone 3, GIS:** decide on PostGIS; map component (MapLibre + OpenStreetMap tiles);
  route drawing; QLDTraffic closures and flood events (official API, needs a key); Bureau of
  Meteorology warnings (licensing check); Geoscience Australia elevation; ABS Remoteness Areas;
  emergency service locations; coverage only where a licence permits (carrier maps generally
  don't); every signal with source, observation time and freshness, confirmed vs modelled kept
  apart; offline map packs.
* **Milestone 4, monitoring:** check-in receipt with three states (pressed, received by server,
  acknowledged by monitor), server-side schedule on Celery beat, overdue detection, escalation
  ladder with retries and delivery tracking, idempotent event handling, supervisor live board,
  incident records. End-to-end alert testing before anything is advertised.
* **Milestone 5, offline:** installable worker app, encrypted local copy of assigned journeys,
  offline checklist, queued updates clearly marked "not sent", sync, shared-device rules.
* **Milestone 6, commercial:** evidence uploads (reuse the documents module and virus scanning),
  retention settings and purge job, tenant admin polish, richer reports, provider-independent
  satellite device adapters (Garmin inReach and others only through documented, licensed APIs;
  mocks until then), API access, payments.

## 7. Production-readiness checklist

- [x] Tenant isolation by RLS, tested through the API and the privilege map
- [x] Role checks in the backend for every action; no self-approval
- [x] Append-only audit trail and revision snapshots
- [x] Limitations shown in the app and on the PDF
- [ ] Legal review of the limitation wording and WHS review of the default risk library
- [ ] Organisation privacy notice for worker personal and location data
- [ ] Check-in monitoring built and tested end to end (Milestone 4)
- [ ] External data sources licensed and connected (Milestone 3)
- [ ] Offline mode (Milestone 5)
- [ ] Retention schedule (Milestone 6)

## 8. Install and deploy

Nothing beyond the usual: merging runs CI, then the deploy workflow pulls, rebuilds, runs
migration 0035 and restarts. No new environment variables or services. After deploy, an
organisation administrator of a business organisation opens **RemoteSafe** in the header and
turns it on. Staff can change an organisation's tier with
`PUT /v1/admin/remotesafe/organisations/{id}/tier`.
