"use client";

import type {
  ApplicationOut,
  InspectionDetailOut,
  InspectionOut,
  MaintenanceOut,
  RentalOut,
  TenancyOut,
} from "@approvalready/shared-types";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";
import { formatDateTime } from "@/lib/labels";
import {
  APPLICATION_STATUS_LABELS,
  INSPECTION_KIND_LABELS,
  INSPECTION_STATUS_LABELS,
  LISTING_LABELS,
  MAINTENANCE_STATUS_LABELS,
  PRIORITY_LABELS,
  RENT_PERIOD_LABELS,
  TENANCY_STATUS_LABELS,
  checksSummary,
  localDateTime,
  money,
} from "@/lib/property";
import { formatDate, parseDollars } from "@/lib/questionnaire";

type Props = {
  organisationId: string;
  projectId: string;
  projectTitle: string;
  rental: RentalOut;
  applications: ApplicationOut[];
  tenancies: TenancyOut[];
  inspections: InspectionOut[];
  maintenance: MaintenanceOut[];
  canWrite: boolean;
};

type Result<T> = { ok: true; data: T } | { ok: false; message: string };

function text(form: FormData, name: string): string | null {
  return String(form.get(name) ?? "").trim() || null;
}

function cents(form: FormData, name: string): number | null | "invalid" {
  const parsed = parseDollars(String(form.get(name) ?? ""));
  if ("error" in parsed) return "invalid";
  return typeof parsed.value === "number" ? parsed.value : null;
}

function count(form: FormData, name: string): number | null {
  const value = text(form, name);
  return value === null ? null : Number(value);
}

/** RentReady: the listing, applications (no scores), tenancies, inspections, maintenance. */
export function RentalWorkspace({ organisationId, projectId, canWrite, ...props }: Props) {
  const router = useRouter();
  const [rental, setRental] = useState(props.rental);
  const [applications, setApplications] = useState(props.applications);
  const [tenancies, setTenancies] = useState(props.tenancies);
  const [inspections, setInspections] = useState(props.inspections);
  const [maintenance, setMaintenance] = useState(props.maintenance);
  const [leasing, setLeasing] = useState<ApplicationOut | "direct" | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const org = `/organisations/${organisationId}`;
  const base = `${org}/projects/${projectId}/rental`;

  async function run<T>(call: () => Promise<Result<T>>): Promise<T | undefined> {
    setBusy(true);
    setError(null);
    const result = await call();
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return undefined;
    }
    return result.data;
  }

  async function refresh() {
    const [r, a] = await Promise.all([
      apiRequest<RentalOut>("GET", base),
      apiRequest<ApplicationOut[]>("GET", `${base}/applications`),
    ]);
    if (r.ok) setRental(r.data);
    if (a.ok) setApplications(a.data);
  }

  async function saveListing(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const rent = cents(form, "rent");
    if (rent === "invalid") {
      setError("Enter the rent in dollars, for example 650.");
      return;
    }
    const updated = await run(() =>
      apiRequest<RentalOut>("PATCH", base, {
        bedrooms: count(form, "bedrooms"),
        bathrooms: count(form, "bathrooms"),
        parking: count(form, "parking"),
        furnished: form.get("furnished") === "on",
        pets_considered: form.get("pets") === "on",
        listing_status: text(form, "listing_status"),
        headline: text(form, "headline"),
        description: text(form, "description"),
        rent_cents: rent,
        rent_period: text(form, "rent_period"),
        available_from: text(form, "available_from"),
      }),
    );
    if (updated) setRental(updated);
  }

  async function addApplication(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const created = await run(() =>
      apiRequest<ApplicationOut>("POST", `${base}/applications`, {
        applicant_name: text(form, "applicant_name"),
        applicant_contact: text(form, "applicant_contact"),
        household_size: count(form, "household_size"),
        preferred_start_on: text(form, "preferred_start_on"),
      }),
    );
    if (created) {
      setApplications((a) => [...a, created]);
      formElement.reset();
    }
  }

  async function updateApplication(application: ApplicationOut, body: Record<string, unknown>) {
    const updated = await run(() =>
      apiRequest<ApplicationOut>("PATCH", `${org}/tenant-applications/${application.id}`, body),
    );
    if (updated) setApplications((a) => a.map((x) => (x.id === updated.id ? updated : x)));
  }

  async function recordTenancy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const rent = cents(form, "rent");
    const bond = cents(form, "bond");
    if (rent === "invalid" || rent === null || bond === "invalid") {
      setError("Enter the rent and bond in dollars, for example 650.");
      return;
    }
    const body = {
      tenant_names: text(form, "tenant_names"),
      tenant_contact: text(form, "tenant_contact"),
      start_on: text(form, "start_on"),
      end_on: text(form, "end_on"),
      rent_cents: rent,
      rent_period: text(form, "rent_period"),
      bond_cents: bond,
      bond_lodged_on: text(form, "bond_lodged_on"),
      next_rent_review_on: text(form, "next_rent_review_on"),
    };
    const url =
      leasing && leasing !== "direct"
        ? `${org}/tenant-applications/${leasing.id}/tenancy`
        : `${base}/tenancies`;
    const created = await run(() => apiRequest<TenancyOut>("POST", url, body));
    if (created) {
      setTenancies((t) => [created, ...t]);
      setLeasing(null);
      await refresh();
    }
  }

  async function updateTenancy(tenancy: TenancyOut, body: Record<string, unknown>) {
    const updated = await run(() =>
      apiRequest<TenancyOut>("PATCH", `${org}/tenancies/${tenancy.id}`, body),
    );
    if (updated) {
      setTenancies((t) => t.map((x) => (x.id === updated.id ? updated : x)));
      await refresh();
    }
  }

  async function scheduleInspection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const created = await run(() =>
      apiRequest<InspectionDetailOut>("POST", `${base}/inspections`, {
        kind: text(form, "kind"),
        scheduled_at: localDateTime(String(form.get("day")), String(form.get("time") ?? "")),
        tenancy_id: rental.current_tenancy_id,
      }),
    );
    if (created) {
      setInspections((i) => [created, ...i]);
      router.push(`/projects/${projectId}/rental/inspections/${created.id}`);
    }
  }

  async function addMaintenance(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const created = await run(() =>
      apiRequest<MaintenanceOut>("POST", `${base}/maintenance`, {
        title: text(form, "title"),
        detail: text(form, "detail"),
        priority: text(form, "priority"),
        reported_by: text(form, "reported_by"),
        tenancy_id: rental.current_tenancy_id,
      }),
    );
    if (created) {
      setMaintenance((m) => [created, ...m]);
      formElement.reset();
    }
  }

  async function setMaintenanceStatus(item: MaintenanceOut, status: string) {
    const updated = await run(() =>
      apiRequest<MaintenanceOut>("PATCH", `${org}/maintenance-items/${item.id}`, { status }),
    );
    if (updated) setMaintenance((m) => m.map((x) => (x.id === updated.id ? updated : x)));
  }

  const leasingFrom = leasing && leasing !== "direct" ? leasing : null;

  return (
    <div className="workspace">
      <section className="page-head" aria-labelledby="rental-title">
        <div>
          <h1 id="rental-title" className="page-title">
            Your rental
          </h1>
          <p className="muted">
            {props.projectTitle} ·{" "}
            <span className="status">{LISTING_LABELS[rental.listing_status]}</span>
            {rental.rent_cents
              ? ` · ${money(rental.rent_cents)} ${RENT_PERIOD_LABELS[rental.rent_period]}`
              : ""}
          </p>
        </div>
      </section>
      <p className="notice">
        What the law asks of a landlord (bonds, notices, minimum standards) is in your
        assessment and checklists on the <Link href={`/projects/${projectId}`}>project page</Link>.
        Reminders here point you there; they don&apos;t replace the rules.
      </p>
      <FormError message={error} />

      <section className="panel" aria-labelledby="listing-title">
        <h2 id="listing-title" className="section-title">
          Property and listing
        </h2>
        {canWrite ? (
          <form className="form" onSubmit={saveListing} aria-label="Property and listing">
            <div className="field-row">
              <label>
                Bedrooms
                <input name="bedrooms" type="number" min={0} max={30} defaultValue={rental.bedrooms ?? ""} />
              </label>
              <label>
                Bathrooms
                <input name="bathrooms" type="number" min={0} max={30} defaultValue={rental.bathrooms ?? ""} />
              </label>
              <label>
                Car spaces
                <input name="parking" type="number" min={0} max={30} defaultValue={rental.parking ?? ""} />
              </label>
            </div>
            <label className="option">
              <input type="checkbox" name="furnished" defaultChecked={rental.furnished ?? false} />{" "}
              Furnished
            </label>
            <label className="option">
              <input type="checkbox" name="pets" defaultChecked={rental.pets_considered ?? false} />{" "}
              Pets considered
            </label>
            <div className="field-row">
              <label>
                Rent
                <input
                  name="rent"
                  inputMode="decimal"
                  defaultValue={rental.rent_cents ? String(rental.rent_cents / 100) : ""}
                />
              </label>
              <label>
                Per
                <select name="rent_period" defaultValue={rental.rent_period}>
                  {Object.entries(RENT_PERIOD_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label.replace("per ", "")}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Available from
                <input name="available_from" type="date" defaultValue={rental.available_from ?? ""} />
              </label>
            </div>
            <label>
              Headline (optional)
              <input name="headline" maxLength={200} defaultValue={rental.headline ?? ""} />
            </label>
            <label>
              Description (optional)
              <textarea name="description" maxLength={4000} defaultValue={rental.description ?? ""} />
            </label>
            <label>
              Listing
              <select name="listing_status" defaultValue={rental.listing_status}>
                {Object.entries(LISTING_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <p className="hint">An advertised rental states one fixed rent, never a range.</p>
            <button type="submit" className="button button-secondary" disabled={busy}>
              Save
            </button>
          </form>
        ) : (
          <p>
            {rental.bedrooms ?? "?"} bedrooms · {rental.bathrooms ?? "?"} bathrooms
          </p>
        )}
      </section>

      <section className="panel" aria-labelledby="applications-title">
        <h2 id="applications-title" className="section-title">
          Applications
        </h2>
        <p className="muted">
          Listed in the order they arrived. Record which documents each applicant has given you;
          ApprovalReady never scores or ranks applicants. You decide.
        </p>
        {applications.length === 0 ? <p className="muted">No applications recorded.</p> : null}
        <ul className="task-list">
          {applications.map((a) => (
            <li key={a.id} className="card">
              <p>
                <strong>{a.applicant_name}</strong>{" "}
                <span className="status">{APPLICATION_STATUS_LABELS[a.status]}</span>
                <span className="muted">
                  {" "}
                  · received {formatDate(a.received_on)}
                  {a.household_size ? ` · ${a.household_size} people` : ""}
                  {a.preferred_start_on ? ` · from ${formatDate(a.preferred_start_on)}` : ""}
                  {a.applicant_contact ? ` · ${a.applicant_contact}` : ""}
                </span>
              </p>
              <p className="muted">{checksSummary(a)}</p>
              <ul className="options">
                {a.checks.map((c) => (
                  <li key={c.key}>
                    <label className="option">
                      <input
                        type="checkbox"
                        checked={c.provided === true}
                        disabled={!canWrite || busy}
                        onChange={(e) =>
                          updateApplication(a, { checks: { [c.key]: e.target.checked } })
                        }
                      />{" "}
                      {c.label}
                    </label>
                  </li>
                ))}
              </ul>
              {canWrite && !a.tenancy_id ? (
                <div className="button-row tight">
                  {a.status === "RECEIVED" ? (
                    <button
                      type="button"
                      className="button-link"
                      disabled={busy}
                      onClick={() => updateApplication(a, { status: "SHORTLISTED" })}
                    >
                      Shortlist
                    </button>
                  ) : null}
                  {["RECEIVED", "SHORTLISTED"].includes(a.status) ? (
                    <>
                      <button
                        type="button"
                        className="button button-secondary"
                        disabled={busy}
                        onClick={() => setLeasing(a)}
                      >
                        Approve and record the tenancy
                      </button>
                      <button
                        type="button"
                        className="button-link"
                        disabled={busy}
                        onClick={() => updateApplication(a, { status: "DECLINED" })}
                      >
                        Decline
                      </button>
                    </>
                  ) : null}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
        {canWrite ? (
          <details>
            <summary>Record an application</summary>
            <form className="form" onSubmit={addApplication} aria-label="Record an application">
              <div className="field-row">
                <label>
                  Applicant
                  <input name="applicant_name" required maxLength={200} />
                </label>
                <label>
                  Phone or email (optional)
                  <input name="applicant_contact" maxLength={200} />
                </label>
              </div>
              <div className="field-row">
                <label>
                  People in the household (optional)
                  <input name="household_size" type="number" min={1} max={30} />
                </label>
                <label>
                  Would like to start (optional)
                  <input name="preferred_start_on" type="date" />
                </label>
              </div>
              <button type="submit" className="button button-secondary" disabled={busy}>
                Save application
              </button>
            </form>
          </details>
        ) : null}
      </section>

      <section className="panel" aria-labelledby="tenancies-title">
        <h2 id="tenancies-title" className="section-title">
          Tenancies
        </h2>
        {tenancies.length === 0 ? <p className="muted">No tenancies recorded.</p> : null}
        <ul className="task-list">
          {tenancies.map((t) => (
            <li key={t.id} className="card">
              <p>
                <strong>{t.tenant_names}</strong>{" "}
                <span className="status">{TENANCY_STATUS_LABELS[t.status]}</span>
              </p>
              <p className="muted">
                {formatDate(t.start_on)} to {t.end_on ? formatDate(t.end_on) : "periodic"} ·{" "}
                {money(t.rent_cents)} {RENT_PERIOD_LABELS[t.rent_period]}
                {t.bond_cents ? ` · bond ${money(t.bond_cents)}` : ""}
                {t.bond_lodged_on ? ` lodged ${formatDate(t.bond_lodged_on)}` : ""}
                {t.next_rent_review_on ? ` · rent review ${formatDate(t.next_rent_review_on)}` : ""}
                {t.ended_on ? ` · moved out ${formatDate(t.ended_on)}` : ""}
              </p>
              {t.bond_to_lodge ? (
                <p className="notice">No bond lodgement recorded yet.</p>
              ) : null}
              {canWrite && !t.ended_on ? (
                <TenancyActions tenancy={t} busy={busy} onSave={(body) => updateTenancy(t, body)} />
              ) : null}
            </li>
          ))}
        </ul>
        {canWrite && leasing === null ? (
          <button
            type="button"
            className="button button-secondary"
            disabled={busy}
            onClick={() => setLeasing("direct")}
          >
            Record a tenancy
          </button>
        ) : null}
        {canWrite && leasing !== null ? (
          <form className="form" onSubmit={recordTenancy} aria-label="Record a tenancy">
            <h3 className="subsection-title">
              {leasingFrom ? `Tenancy for ${leasingFrom.applicant_name}` : "New tenancy"}
            </h3>
            <div className="field-row">
              <label>
                Tenant names
                <input
                  name="tenant_names"
                  required
                  maxLength={300}
                  defaultValue={leasingFrom?.applicant_name ?? ""}
                />
              </label>
              <label>
                Phone or email (optional)
                <input
                  name="tenant_contact"
                  maxLength={200}
                  defaultValue={leasingFrom?.applicant_contact ?? ""}
                />
              </label>
            </div>
            <div className="field-row">
              <label>
                Starts
                <input
                  name="start_on"
                  type="date"
                  required
                  defaultValue={leasingFrom?.preferred_start_on ?? rental.available_from ?? ""}
                />
              </label>
              <label>
                Ends (leave blank if periodic)
                <input name="end_on" type="date" />
              </label>
            </div>
            <div className="field-row">
              <label>
                Rent
                <input
                  name="rent"
                  required
                  inputMode="decimal"
                  defaultValue={rental.rent_cents ? String(rental.rent_cents / 100) : ""}
                />
              </label>
              <label>
                Per
                <select name="rent_period" defaultValue={rental.rent_period}>
                  {Object.entries(RENT_PERIOD_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label.replace("per ", "")}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Bond (optional)
                <input name="bond" inputMode="decimal" />
              </label>
            </div>
            <div className="field-row">
              <label>
                Bond lodged on (optional)
                <input name="bond_lodged_on" type="date" />
              </label>
              <label>
                Next rent review (optional)
                <input name="next_rent_review_on" type="date" />
              </label>
            </div>
            <p className="hint">
              We&apos;ll remind you to lodge the bond, before the lease ends and before a rent
              review.
            </p>
            <div className="button-row tight">
              <button type="submit" className="button" disabled={busy}>
                Save tenancy
              </button>
              <button
                type="button"
                className="button button-secondary"
                disabled={busy}
                onClick={() => setLeasing(null)}
              >
                Cancel
              </button>
            </div>
          </form>
        ) : null}
      </section>

      <section className="panel" aria-labelledby="inspections-title">
        <h2 id="inspections-title" className="section-title">
          Inspections
        </h2>
        <p className="muted">Open an inspection on your phone and go room by room.</p>
        {inspections.length === 0 ? <p className="muted">No inspections yet.</p> : null}
        <ul className="task-list">
          {inspections.map((i) => (
            <li key={i.id} className="task">
              <Link href={`/projects/${projectId}/rental/inspections/${i.id}`}>
                {INSPECTION_KIND_LABELS[i.kind]} inspection, {formatDateTime(i.scheduled_at)}
              </Link>
              <span className="muted">
                {INSPECTION_STATUS_LABELS[i.status]} · {i.items_checked} of {i.items_total} checked
              </span>
            </li>
          ))}
        </ul>
        {canWrite ? (
          <form className="form inline-form" onSubmit={scheduleInspection} aria-label="Schedule an inspection">
            <label>
              Kind
              <select name="kind" defaultValue="ROUTINE">
                {Object.entries(INSPECTION_KIND_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              On
              <input name="day" type="date" required />
            </label>
            <label>
              At
              <input name="time" type="time" defaultValue="10:00" />
            </label>
            <button type="submit" className="button button-secondary" disabled={busy}>
              Schedule
            </button>
          </form>
        ) : null}
      </section>

      <section className="panel" aria-labelledby="maintenance-title">
        <h2 id="maintenance-title" className="section-title">
          Maintenance
        </h2>
        {maintenance.length === 0 ? <p className="muted">Nothing reported.</p> : null}
        <ul className="task-list">
          {maintenance.map((m) => (
            <li key={m.id} className="task">
              <span>
                {m.priority !== "ROUTINE" ? (
                  <span className="badge">{PRIORITY_LABELS[m.priority]}</span>
                ) : null}{" "}
                <strong>{m.title}</strong>
                <span className="muted">
                  {" "}
                  · reported {formatDate(m.reported_on)}
                  {m.reported_by ? ` by ${m.reported_by}` : ""}
                  {m.resolved_on ? ` · fixed ${formatDate(m.resolved_on)}` : ""}
                </span>
                {m.detail ? <span className="muted"> · {m.detail}</span> : null}
              </span>
              {canWrite ? (
                <label>
                  <span className="visually-hidden">Status of {m.title}</span>
                  <select
                    value={m.status}
                    disabled={busy}
                    onChange={(e) => setMaintenanceStatus(m, e.target.value)}
                  >
                    {Object.entries(MAINTENANCE_STATUS_LABELS).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
              ) : (
                <span className="status">{MAINTENANCE_STATUS_LABELS[m.status]}</span>
              )}
            </li>
          ))}
        </ul>
        {canWrite ? (
          <details>
            <summary>Report a repair</summary>
            <form className="form" onSubmit={addMaintenance} aria-label="Report a repair">
              <div className="field-row">
                <label>
                  What needs fixing
                  <input name="title" required maxLength={200} />
                </label>
                <label>
                  How urgent
                  <select name="priority" defaultValue="ROUTINE">
                    {Object.entries(PRIORITY_LABELS).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Reported by (optional)
                  <input name="reported_by" maxLength={200} />
                </label>
              </div>
              <label>
                Details (optional)
                <textarea name="detail" maxLength={2000} />
              </label>
              <button type="submit" className="button button-secondary" disabled={busy}>
                Save
              </button>
            </form>
          </details>
        ) : null}
      </section>
    </div>
  );
}

function TenancyActions({
  tenancy,
  busy,
  onSave,
}: {
  tenancy: TenancyOut;
  busy: boolean;
  onSave: (body: Record<string, unknown>) => void;
}) {
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const body: Record<string, unknown> = {};
    for (const name of ["bond_lodged_on", "bond_reference", "next_rent_review_on", "end_on", "ended_on"]) {
      const value = text(form, name);
      if (value !== null) body[name] = value;
    }
    if (Object.keys(body).length > 0) onSave(body);
  }
  return (
    <details>
      <summary>Update this tenancy</summary>
      <form className="form" onSubmit={submit} aria-label={`Update the tenancy for ${tenancy.tenant_names}`}>
        {tenancy.bond_to_lodge ? (
          <div className="field-row">
            <label>
              Bond lodged on
              <input name="bond_lodged_on" type="date" />
            </label>
            <label>
              Bond number (optional)
              <input name="bond_reference" maxLength={60} />
            </label>
          </div>
        ) : null}
        <div className="field-row">
          <label>
            Lease ends
            <input name="end_on" type="date" defaultValue={tenancy.end_on ?? ""} />
          </label>
          <label>
            Next rent review
            <input name="next_rent_review_on" type="date" defaultValue={tenancy.next_rent_review_on ?? ""} />
          </label>
          <label>
            Tenant moved out on
            <input name="ended_on" type="date" />
          </label>
        </div>
        <button type="submit" className="button button-secondary" disabled={busy}>
          Save changes
        </button>
      </form>
    </details>
  );
}
