"use client";

import type {
  ControlCheckOut,
  JourneyAssessmentOut,
  JourneyEventOut,
  JourneyOut,
  RsMemberOut,
  RsVehicleOut,
} from "@approvalready/shared-types";
import { type FormEvent, useState } from "react";

import { FormError } from "@/components/auth/FormStatus";
import { JourneyForm } from "@/components/remotesafe/JourneyForm";
import { apiRequest } from "@/lib/client-api";
import { formatDateTime } from "@/lib/labels";
import {
  ACTION_LABELS,
  CHECKIN_METHOD_LABELS,
  CLOSURE_LABELS,
  CONTROL_GROUP_LABELS,
  COVERAGE_LABELS,
  NOTE_REQUIRED,
  RATING_LABELS,
  STATUS_LABELS,
  SURFACE_LABELS,
  checkinTimes,
  label,
  ratingClass,
  toLocalInput,
} from "@/lib/remotesafe";

type Props = {
  base: string;
  meId: string;
  isWhsAdmin: boolean;
  journey: JourneyOut;
  assessment: JourneyAssessmentOut;
  controls: ControlCheckOut[];
  events: JourneyEventOut[];
  members: RsMemberOut[];
  vehicles: RsVehicleOut[];
  timezones: Record<string, string>;
  limitations: string[];
};

type LegDraft = {
  origin: string;
  destination: string;
  departs_at: string;
  arrives_at: string;
  timezone: string;
  distance_km: string;
  road_surface: string;
  mobile_coverage: string;
  crossings: string;
  closure_status: string;
  closure_source: string;
};

function legDrafts(journey: JourneyOut): LegDraft[] {
  return journey.legs.map((l) => ({
    origin: l.origin,
    destination: l.destination,
    departs_at: toLocalInput(l.departs.utc, l.timezone),
    arrives_at: toLocalInput(l.arrives.utc, l.timezone),
    timezone: l.timezone,
    distance_km: l.distance_km?.toString() ?? "",
    road_surface: l.road_surface,
    mobile_coverage: l.mobile_coverage,
    crossings: String(l.crossings),
    closure_status: l.closure_status,
    closure_source: l.closure_source ?? "",
  }));
}

function emptyLeg(journey: JourneyOut, previous?: LegDraft): LegDraft {
  return {
    origin: previous?.destination ?? journey.origin,
    destination: "",
    departs_at: previous?.arrives_at ?? toLocalInput(journey.departs.utc, journey.timezone),
    arrives_at: "",
    timezone: previous?.timezone ?? journey.timezone,
    distance_km: "",
    road_surface: "UNKNOWN",
    mobile_coverage: "UNKNOWN",
    crossings: "0",
    closure_status: "NOT_CHECKED",
    closure_source: "",
  };
}

function Choice({
  name,
  value,
  options,
  onChange,
  labelText,
}: {
  name: string;
  value: string;
  options: Record<string, string>;
  onChange: (v: string) => void;
  labelText: string;
}) {
  return (
    <label>
      {labelText}
      <select name={name} value={value} onChange={(e) => onChange(e.target.value)}>
        {Object.entries(options).map(([k, v]) => (
          <option key={k} value={k}>
            {v}
          </option>
        ))}
      </select>
    </label>
  );
}

/** One journey: plan, route, check-ins, risk assessment, controls, approval and history. */
export function JourneyWorkspace({ base, meId, isWhsAdmin, members, vehicles, ...props }: Props) {
  const [journey, setJourney] = useState(props.journey);
  const [assessment, setAssessment] = useState(props.assessment);
  const [controls, setControls] = useState(props.controls);
  const [events, setEvents] = useState(props.events);
  const [legs, setLegs] = useState<LegDraft[]>(() => legDrafts(props.journey));
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [alternative, setAlternative] = useState("");
  const [exceptionFor, setExceptionFor] = useState<string | null>(null);
  const [exceptionReason, setExceptionReason] = useState("");
  const url = `${base}/journeys/${journey.id}`;
  const editable = journey.can_edit;

  async function reload(updated?: JourneyOut) {
    const [j, a, c, e] = await Promise.all([
      updated ? Promise.resolve({ ok: true as const, status: 200, data: updated }) : apiRequest<JourneyOut>("GET", url),
      apiRequest<JourneyAssessmentOut>("GET", `${url}/assessment`),
      apiRequest<ControlCheckOut[]>("GET", `${url}/controls`),
      apiRequest<JourneyEventOut[]>("GET", `${url}/events`),
    ]);
    if (j.ok) {
      setJourney(j.data);
      setLegs(legDrafts(j.data));
    }
    if (a.ok) setAssessment(a.data);
    if (c.ok) setControls(c.data);
    if (e.ok) setEvents(e.data);
  }

  async function call<T>(method: "POST" | "PUT", path: string, body: unknown): Promise<T | null> {
    setBusy(true);
    setError(null);
    const result = await apiRequest<T>(method, path, body);
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return null;
    }
    return result.data;
  }

  async function saveLegs(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const updated = await call<JourneyOut>("PUT", `${url}/legs`, {
      legs: legs.map((l) => ({
        origin: l.origin,
        destination: l.destination,
        departs_at: l.departs_at,
        arrives_at: l.arrives_at,
        timezone: l.timezone,
        distance_km: l.distance_km ? Number(l.distance_km) : null,
        road_surface: l.road_surface,
        mobile_coverage: l.mobile_coverage,
        crossings: Number(l.crossings || 0),
        closure_status: l.closure_status,
        closure_source: l.closure_source || null,
      })),
    });
    if (updated) await reload(updated);
  }

  async function planCheckins() {
    const interval = journey.checkin_interval_minutes ?? 120;
    const end = journey.returns ?? journey.arrives;
    const times = checkinTimes(
      toLocalInput(journey.departs.utc, journey.timezone),
      toLocalInput(end.utc, journey.timezone),
      interval,
    );
    const method = journey.comms_sat_messenger ? "SATELLITE_MESSAGE" : "PHONE_CALL";
    const updated = await call<JourneyOut>("PUT", `${url}/checkins`, {
      checkins: times.map((due_at) => ({ due_at, method })),
    });
    if (updated) await reload(updated);
  }

  async function clearCheckins() {
    const updated = await call<JourneyOut>("PUT", `${url}/checkins`, { checkins: [] });
    if (updated) await reload(updated);
  }

  async function setControl(key: string, status: string) {
    const updated = await call<ControlCheckOut[]>("PUT", `${url}/controls/${key}`, { status });
    if (updated) {
      setControls(updated);
      await reload();
    }
  }

  async function recordException(key: string) {
    if (exceptionReason.trim().length < 10) {
      setError("Explain the exception in at least 10 characters.");
      return;
    }
    const updated = await call<ControlCheckOut[]>("POST", `${url}/controls/${key}/exception`, {
      reason: exceptionReason,
    });
    if (updated) {
      setExceptionFor(null);
      setExceptionReason("");
      await reload();
    }
  }

  async function act(action: string) {
    if (NOTE_REQUIRED.has(action) && !note.trim()) {
      setError("Add a note first: say what needs to change, or why you're escalating.");
      return;
    }
    const body =
      action === "approve"
        ? { note: note || null, critical_alternative_process: alternative || null }
        : { note: note || null };
    const path = action === "approve" ? `${url}/approve` : `${url}/${action}`;
    const updated = await call<JourneyOut>("POST", path, body);
    if (updated) {
      setNote("");
      setAlternative("");
      await reload(updated);
    }
  }

  const grouped = Object.keys(CONTROL_GROUP_LABELS).map((g) => ({
    group: g,
    rows: controls.filter((c) => c.group === g),
  }));
  const zoneNames = props.timezones;

  return (
    <div className="workspace">
      <div className="page-head">
        <div>
          <h1 className="page-title">{journey.title}</h1>
          <p className="muted">
            {journey.reference} · revision {journey.revision} · {journey.worker.display_name}
          </p>
        </div>
        <span className={`status status-${journey.status.toLowerCase()}`}>
          {label(STATUS_LABELS, journey.status)}
        </span>
      </div>
      <FormError message={error} />

      <section className="panel" aria-label="Risk outcome">
        <h2 className="section-title">
          Risk: <span className={ratingClass(assessment.outcome)}>{label(RATING_LABELS, assessment.outcome)}</span>
        </h2>
        <p>{assessment.pathway}</p>
        {assessment.stop_conditions.map((s) => (
          <p key={s.key} className="notice notice-error" role="alert">
            <strong>Stop:</strong> {s.reason}
          </p>
        ))}
        {journey.blockers.length ? (
          <>
            <h3 className="subsection-title">Before the next step</h3>
            <ul>
              {journey.blockers.map((b) => (
                <li key={b}>{b}</li>
              ))}
            </ul>
          </>
        ) : null}
        {journey.allowed_actions.length ? (
          <div className="form">
            {journey.allowed_actions.includes("approve") && assessment.outcome === "CRITICAL" ? (
              <label>
                Documented alternative process (needed to approve a critical journey)
                <textarea
                  value={alternative}
                  onChange={(e) => setAlternative(e.target.value)}
                  maxLength={2000}
                />
              </label>
            ) : null}
            <label>
              Note (optional; needed to ask for changes or escalate)
              <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} />
            </label>
            <div className="button-row">
              {journey.allowed_actions.map((a) => (
                <button
                  key={a}
                  type="button"
                  className={a === "cancel" || a === "archive" ? "button button-secondary" : "button"}
                  disabled={busy}
                  onClick={() => act(a)}
                >
                  {label(ACTION_LABELS, a)}
                </button>
              ))}
            </div>
          </div>
        ) : null}
        <p className="form-aside">
          <a href={`/api/v1${url}/plan.pdf`}>Download the journey plan (PDF)</a> ·{" "}
          <a href={`/api/v1${url}/export.json`}>Export (JSON)</a>
        </p>
      </section>

      <section className="panel" aria-label="Plan">
        <h2 className="section-title">Plan</h2>
        <dl className="details">
          <dt>Route</dt>
          <dd>
            {journey.origin} to {journey.destination}
          </dd>
          <dt>Departs</dt>
          <dd>{journey.departs.local}</dd>
          <dt>Arrives</dt>
          <dd>{journey.arrives.local}</dd>
          {journey.returns ? (
            <>
              <dt>Returns</dt>
              <dd>{journey.returns.local}</dd>
            </>
          ) : null}
          <dt>Supervisor</dt>
          <dd>{journey.supervisor?.display_name ?? "Not chosen"}</dd>
          <dt>Journey monitor</dt>
          <dd>{journey.monitor?.display_name ?? "Not chosen"}</dd>
          <dt>Vehicle</dt>
          <dd>
            {journey.vehicle_description ?? "Not set"}
            {journey.vehicle_registration ? ` (${journey.vehicle_registration})` : ""},{" "}
            {journey.occupants} on board
          </dd>
        </dl>
        {editable ? (
          editing ? (
            <JourneyForm
              base={base}
              members={members}
              vehicles={vehicles}
              timezones={zoneNames}
              defaultTimezone={journey.timezone}
              meId={meId}
              canPlanForOthers={false}
              journey={journey}
              onSaved={async (j) => {
                setEditing(false);
                await reload(j);
              }}
            />
          ) : (
            <button type="button" className="button button-secondary" onClick={() => setEditing(true)}>
              Edit details
            </button>
          )
        ) : null}
        {journey.status === "APPROVED" && editable ? (
          <p className="hint">
            Changing the route, vehicle, times, people or communications sends the plan back for
            approval and clears the pre-departure checklist.
          </p>
        ) : null}
      </section>

      <section className="panel" aria-label="Route legs">
        <h2 className="section-title">Route legs</h2>
        <p className="hint">
          Record what you know about each leg and where you checked it (for closures, say the
          source, e.g. QLDTraffic). RemoteSafe doesn&apos;t look up roads or coverage yet.
        </p>
        <form method="post" className="form" onSubmit={saveLegs} aria-label="Route legs">
          {legs.map((leg, i) => {
            const set = (patch: Partial<LegDraft>) =>
              setLegs((all) => all.map((l, j) => (j === i ? { ...l, ...patch } : l)));
            return (
              <fieldset key={i} className="card" disabled={!editable}>
                <legend>Leg {i + 1}</legend>
                <div className="field-row">
                  <label>
                    From
                    <input value={leg.origin} required onChange={(e) => set({ origin: e.target.value })} />
                  </label>
                  <label>
                    To
                    <input
                      value={leg.destination}
                      required
                      onChange={(e) => set({ destination: e.target.value })}
                    />
                  </label>
                  <label>
                    Distance (km)
                    <input
                      type="number"
                      min={1}
                      value={leg.distance_km}
                      onChange={(e) => set({ distance_km: e.target.value })}
                    />
                  </label>
                </div>
                <div className="field-row">
                  <label>
                    Departs
                    <input
                      type="datetime-local"
                      required
                      value={leg.departs_at}
                      onChange={(e) => set({ departs_at: e.target.value })}
                    />
                  </label>
                  <label>
                    Arrives
                    <input
                      type="datetime-local"
                      required
                      value={leg.arrives_at}
                      onChange={(e) => set({ arrives_at: e.target.value })}
                    />
                  </label>
                  <Choice
                    name="timezone"
                    labelText="Time zone"
                    value={leg.timezone}
                    options={zoneNames}
                    onChange={(v) => set({ timezone: v })}
                  />
                </div>
                <div className="field-row">
                  <Choice
                    name="road_surface"
                    labelText="Road surface"
                    value={leg.road_surface}
                    options={SURFACE_LABELS}
                    onChange={(v) => set({ road_surface: v })}
                  />
                  <Choice
                    name="mobile_coverage"
                    labelText="Mobile coverage"
                    value={leg.mobile_coverage}
                    options={COVERAGE_LABELS}
                    onChange={(v) => set({ mobile_coverage: v })}
                  />
                  <label>
                    Creek or causeway crossings
                    <input
                      type="number"
                      min={0}
                      value={leg.crossings}
                      onChange={(e) => set({ crossings: e.target.value })}
                    />
                  </label>
                </div>
                <div className="field-row">
                  <Choice
                    name="closure_status"
                    labelText="Road closures"
                    value={leg.closure_status}
                    options={CLOSURE_LABELS}
                    onChange={(v) => set({ closure_status: v })}
                  />
                  <label>
                    Where you checked
                    <input
                      value={leg.closure_source}
                      placeholder="QLDTraffic"
                      onChange={(e) => set({ closure_source: e.target.value })}
                    />
                  </label>
                </div>
                {editable ? (
                  <button
                    type="button"
                    className="button-link"
                    onClick={() => setLegs((all) => all.filter((_, j) => j !== i))}
                  >
                    Remove leg {i + 1}
                  </button>
                ) : null}
              </fieldset>
            );
          })}
          {editable ? (
            <div className="button-row">
              <button
                type="button"
                className="button button-secondary"
                onClick={() => setLegs((all) => [...all, emptyLeg(journey, all[all.length - 1])])}
              >
                Add a leg
              </button>
              <button type="submit" className="button" disabled={busy}>
                Save route
              </button>
            </div>
          ) : null}
        </form>
      </section>

      <section className="panel" aria-label="Check-ins">
        <h2 className="section-title">Planned check-ins</h2>
        <p className="notice notice-warning">
          RemoteSafe doesn&apos;t receive check-ins or raise alarms yet. The journey monitor
          follows this schedule and escalates under your emergency response plan.
        </p>
        {journey.checkins.length ? (
          <ol>
            {journey.checkins.map((c) => (
              <li key={c.position}>
                {c.due.local}
                {c.location ? ` at ${c.location}` : ""} by {label(CHECKIN_METHOD_LABELS, c.method)}
              </li>
            ))}
          </ol>
        ) : (
          <p className="muted">No check-ins planned yet.</p>
        )}
        {editable ? (
          <div className="button-row">
            <button type="button" className="button button-secondary" disabled={busy} onClick={planCheckins}>
              Plan check-ins every {journey.checkin_interval_minutes ?? 120} minutes
            </button>
            {journey.checkins.length ? (
              <button type="button" className="button-link" disabled={busy} onClick={clearCheckins}>
                Clear
              </button>
            ) : null}
          </div>
        ) : null}
      </section>

      <section className="panel" aria-label="Risk assessment">
        <h2 className="section-title">Risk assessment</h2>
        <p className="hint">{assessment.disclaimer}</p>
        {assessment.findings.length === 0 ? (
          <p>No hazards were triggered by the plan as entered.</p>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Hazard</th>
                  <th>Evidence</th>
                  <th>Initial</th>
                  <th>Controls</th>
                  <th>Residual</th>
                  <th>Still to do</th>
                </tr>
              </thead>
              <tbody>
                {assessment.findings.map((f) => (
                  <tr key={f.hazard_key}>
                    <td>
                      <strong>{f.title}</strong>
                      <br />
                      <span className="muted">{f.description}</span>
                    </td>
                    <td>
                      <ul>
                        {f.evidence.map((e, i) => (
                          <li key={i}>
                            {e.fact}: {e.value} <span className="muted">({e.source})</span>
                          </li>
                        ))}
                      </ul>
                    </td>
                    <td>
                      <span className={ratingClass(f.initial_rating)}>{label(RATING_LABELS, f.initial_rating)}</span>{" "}
                      <span className="muted">
                        L{f.likelihood} × C{f.consequence}
                      </span>
                    </td>
                    <td>{f.control_labels.join("; ")}</td>
                    <td>
                      <span className={ratingClass(f.residual_rating)}>{label(RATING_LABELS, f.residual_rating)}</span>{" "}
                      <span className="muted">
                        L{f.residual_likelihood} × C{f.consequence}
                      </span>
                    </td>
                    <td>
                      {f.outstanding.length ? f.outstanding.join("; ") : "Done"}
                      <br />
                      <span className="muted">Responsible: {f.responsible.toLowerCase()}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <details>
          <summary>Where this comes from</summary>
          <ul>
            {assessment.data_sources.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </details>
      </section>

      <section className="panel" aria-label="Pre-departure checklist">
        <h2 className="section-title">Pre-departure checklist</h2>
        {grouped.map(({ group, rows }) => (
          <div key={group}>
            <h3 className="subsection-title">{CONTROL_GROUP_LABELS[group]}</h3>
            <ul className="task-list">
              {rows.map((c) => (
                <li key={c.key} className="task">
                  <div>
                    <strong>{c.label}</strong> {c.mandatory ? <span className="badge">Mandatory</span> : null}
                    <div className="muted">
                      {c.status === "PENDING"
                        ? "Not done"
                        : `${c.status.replace("_", " ").toLowerCase()} by ${c.completed_by_name ?? "someone"} ${
                            c.completed_at ? formatDateTime(c.completed_at) : ""
                          }`}
                      {c.exception_reason ? `: ${c.exception_reason}` : ""}
                    </div>
                  </div>
                  {editable ? (
                    <div className="button-row tight">
                      <button type="button" className="button button-secondary" disabled={busy} onClick={() => setControl(c.key, "DONE")}>
                        Done
                      </button>
                      <button type="button" className="button button-secondary" disabled={busy} onClick={() => setControl(c.key, "FAILED")}>
                        Failed
                      </button>
                      {!c.mandatory ? (
                        <button type="button" className="button-link" disabled={busy} onClick={() => setControl(c.key, "NOT_APPLICABLE")}>
                          Not needed
                        </button>
                      ) : null}
                      {c.mandatory && isWhsAdmin && journey.worker.user_id !== meId ? (
                        <button type="button" className="button-link" disabled={busy} onClick={() => setExceptionFor(c.key)}>
                          Record exception
                        </button>
                      ) : null}
                    </div>
                  ) : null}
                  {exceptionFor === c.key ? (
                    <div className="form">
                      <label>
                        Why it is safe to go without this (recorded in the audit trail)
                        <textarea
                          value={exceptionReason}
                          onChange={(e) => setExceptionReason(e.target.value)}
                          maxLength={1000}
                        />
                      </label>
                      <div className="button-row tight">
                        <button type="button" className="button" disabled={busy} onClick={() => recordException(c.key)}>
                          Record exception
                        </button>
                        <button type="button" className="button-link" onClick={() => setExceptionFor(null)}>
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </section>

      <section className="panel" aria-label="History">
        <h2 className="section-title">History</h2>
        <ul className="card-list">
          {events.map((e, i) => (
            <li key={i}>
              {formatDateTime(e.occurred_at)}: {e.kind.replaceAll("_", " ").toLowerCase()}
              {e.actor_name ? ` by ${e.actor_name}` : ""} (revision {e.revision})
              {e.note ? <span className="muted"> · {e.note}</span> : null}
            </li>
          ))}
        </ul>
      </section>

      <section className="panel" aria-label="Limitations">
        <h2 className="section-title">What RemoteSafe does not do yet</h2>
        <ul>
          {props.limitations.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
        <p>
          In an emergency call <strong>000</strong>.
        </p>
      </section>
    </div>
  );
}
