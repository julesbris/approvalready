"use client";

import type {
  CertificateKind,
  CertificateOut,
  ProjectDetailOut,
  VesselLookupOut,
  VesselOut,
} from "@approvalready/shared-types";
import { type FormEvent, useEffect, useState } from "react";

import { FormError } from "@/components/auth/FormStatus";
import { VesselLookup, VesselRecord } from "@/components/lookups/VesselLookup";
import { apiRequest } from "@/lib/client-api";
import { formatDate } from "@/lib/questionnaire";

type Props = {
  organisationId: string;
  project: ProjectDetailOut;
  vessels: VesselOut[];
  canWrite: boolean;
  onProjectChange: (project: ProjectDetailOut) => void;
};

const VESSEL_TYPES: [string, string][] = [
  ["MOTOR", "Motor boat"],
  ["SAIL", "Sailing vessel"],
  ["PERSONAL_WATERCRAFT", "Personal watercraft (jet ski)"],
  ["PADDLE", "Paddle craft"],
  ["BARGE", "Barge"],
  ["OTHER", "Other"],
];

const PROPULSION: [string, string][] = [
  ["OUTBOARD", "Outboard engine"],
  ["INBOARD", "Inboard engine"],
  ["STERNDRIVE", "Sterndrive"],
  ["JET", "Jet"],
  ["SAIL", "Sail only"],
  ["SAIL_AUXILIARY", "Sail with auxiliary engine"],
  ["MANUAL", "Paddle or oar"],
  ["OTHER", "Other"],
];

export const CERTIFICATE_KINDS: Record<CertificateKind, string> = {
  CERTIFICATE_OF_SURVEY: "Certificate of survey",
  CERTIFICATE_OF_OPERATION: "Certificate of operation",
  EXEMPTION: "Exemption or non-survey approval",
  STATE_REGISTRATION: "State registration",
  OTHER: "Other certificate",
};

const STATE_LABELS: Record<CertificateOut["state"], string> = {
  CURRENT: "Current",
  EXPIRING: "Expires soon",
  EXPIRED: "Expired",
  NO_EXPIRY: "No expiry date",
};

export function vesselLabel(v: VesselOut): string {
  const type = VESSEL_TYPES.find(([value]) => value === v.vessel_type)?.[1] ?? "Vessel";
  const length = v.length_m ? `, ${Number(v.length_m)} m` : "";
  return `${v.name} (${type}${length})${v.uvi ? ` · UVI ${v.uvi}` : ""}`;
}

/** The vessel a project is about: pick or add one, and keep its certificates. */
export function VesselPanel({
  organisationId,
  project,
  canWrite,
  onProjectChange,
  ...props
}: Props) {
  const [vessels, setVessels] = useState(props.vessels);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [found, setFound] = useState<VesselLookupOut | null>(null);
  const [known, setKnown] = useState({ name: "", length_m: "", uvi: "" });
  const org = `/organisations/${organisationId}`;
  const linked = vessels.find((v) => v.id === project.vessel_id) ?? null;
  const field = (name: keyof typeof known) => ({
    name,
    value: known[name],
    onChange: (e: { target: { value: string } }) =>
      setKnown((k) => ({ ...k, [name]: e.target.value })),
  });

  function applyRecord(record: VesselLookupOut) {
    setFound(record);
    setKnown((k) => ({
      name: record.name ?? k.name,
      length_m: record.length_m ?? k.length_m,
      uvi: record.uvi,
    }));
  }

  function closeForm() {
    setAdding(false);
    setFound(null);
    setKnown({ name: "", length_m: "", uvi: "" });
  }

  async function link(vesselId: string | null) {
    setBusy(true);
    setError(null);
    const result = await apiRequest<ProjectDetailOut>("PATCH", `${org}/projects/${project.id}`, {
      vessel_id: vesselId,
    });
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return false;
    }
    onProjectChange(result.data);
    return true;
  }

  async function addVessel(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const text = (name: string) => String(form.get(name) ?? "").trim();
    const whole = (name: string) => (text(name) ? Number(text(name)) : null);
    setBusy(true);
    setError(null);
    const created = await apiRequest<VesselOut>("POST", `${org}/vessels`, {
      name: text("name"),
      vessel_type: text("vessel_type"),
      length_m: text("length_m") || null,
      propulsion: text("propulsion") || null,
      hull_material: text("hull_material") || null,
      max_passengers: whole("max_passengers"),
      crew: whole("crew"),
      operating_area: text("operating_area") || null,
      uvi: text("uvi") || null,
    });
    setBusy(false);
    if (!created.ok) {
      setError(created.message);
      return;
    }
    setVessels((list) => [...list, created.data]);
    if (await link(created.data.id)) closeForm();
  }

  return (
    <section className="panel" aria-labelledby="vessel-title">
      <h2 id="vessel-title" className="section-title">
        Vessel
      </h2>
      <FormError message={error} />
      {linked ? (
        <>
          <p>{vesselLabel(linked)}</p>
          <p className="hint">
            The questionnaire can fill in the vessel&apos;s name, type, length, propulsion, UVI,
            passengers and crew from these details.
          </p>
          {linked.uvi ? (
            <VesselLookup organisationId={organisationId} uvi={linked.uvi} showRecord />
          ) : null}
        </>
      ) : (
        <p className="muted">
          Which vessel is this project about? Saving it here means you only type its details once.
        </p>
      )}
      {canWrite ? (
        <div className="button-row tight">
          {vessels.length > 0 ? (
            <label>
              {linked ? "Change to" : "Choose a vessel"}
              <select
                value={linked?.id ?? ""}
                disabled={busy}
                onChange={(e) => link(e.target.value || null)}
              >
                <option value="">No vessel</option>
                {vessels.map((v) => (
                  <option key={v.id} value={v.id}>
                    {vesselLabel(v)}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {!adding ? (
            <button
              type="button"
              className="button button-secondary"
              disabled={busy}
              onClick={() => setAdding(true)}
            >
              Add a vessel
            </button>
          ) : null}
        </div>
      ) : null}
      {canWrite && adding ? (
        <form className="form" onSubmit={addVessel} aria-label="Add a vessel">
          <VesselLookup organisationId={organisationId} onFound={applyRecord} disabled={busy} />
          {found ? <VesselRecord record={found} /> : null}
          <div className="field-row">
            <label>
              Vessel name
              <input {...field("name")} required maxLength={120} />
            </label>
            <label>
              Type
              <select name="vessel_type" required defaultValue="MOTOR">
                {VESSEL_TYPES.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="field-row">
            <label>
              Overall length in metres (optional)
              <input {...field("length_m")} inputMode="decimal" pattern="[0-9]+(\.[0-9]{1,2})?" />
            </label>
            <label>
              Propulsion (optional)
              <select name="propulsion" defaultValue="">
                <option value="">Not sure yet</option>
                {PROPULSION.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="field-row">
            <label>
              Hull material (optional)
              <input name="hull_material" maxLength={60} />
            </label>
            <label>
              UVI, if it has one
              <input {...field("uvi")} maxLength={20} />
            </label>
          </div>
          <div className="field-row">
            <label>
              Most passengers (optional)
              <input name="max_passengers" type="number" min={0} max={10000} />
            </label>
            <label>
              Crew (optional)
              <input name="crew" type="number" min={0} max={1000} />
            </label>
          </div>
          <label>
            Where it operates (optional)
            <input name="operating_area" maxLength={200} />
          </label>
          <div className="button-row tight">
            <button type="submit" className="button" disabled={busy}>
              Save vessel
            </button>
            <button
              type="button"
              className="button button-secondary"
              disabled={busy}
              onClick={closeForm}
            >
              Cancel
            </button>
          </div>
        </form>
      ) : null}
      {linked ? (
        <Certificates organisationId={organisationId} vessel={linked} canWrite={canWrite} />
      ) : null}
    </section>
  );
}

function Certificates({
  organisationId,
  vessel,
  canWrite,
}: {
  organisationId: string;
  vessel: VesselOut;
  canWrite: boolean;
}) {
  const [certificates, setCertificates] = useState<CertificateOut[] | null>(null);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const org = `/organisations/${organisationId}`;

  useEffect(() => {
    let cancelled = false;
    apiRequest<CertificateOut[]>("GET", `${org}/vessels/${vessel.id}/certificates`).then(
      (result) => {
        if (cancelled) return;
        if (result.ok) setCertificates(result.data);
        else setError(result.message);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [org, vessel.id]);

  async function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const text = (name: string) => String(form.get(name) ?? "").trim() || null;
    setBusy(true);
    setError(null);
    const created = await apiRequest<CertificateOut>(
      "POST",
      `${org}/vessels/${vessel.id}/certificates`,
      {
        kind: text("kind"),
        number: text("number"),
        issuer: text("issuer"),
        issued_on: text("issued_on"),
        expires_on: text("expires_on"),
      },
    );
    setBusy(false);
    if (!created.ok) {
      setError(created.message);
      return;
    }
    setCertificates((list) => [...(list ?? []), created.data]);
    setAdding(false);
  }

  async function remove(certificate: CertificateOut) {
    setBusy(true);
    setError(null);
    const result = await apiRequest("DELETE", `${org}/vessel-certificates/${certificate.id}`);
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    setCertificates((list) => (list ?? []).filter((c) => c.id !== certificate.id));
  }

  return (
    <div aria-labelledby="certificates-title">
      <h3 id="certificates-title" className="subsection-title">
        Certificates
      </h3>
      <FormError message={error} />
      {certificates === null ? (
        <p className="muted">Loading…</p>
      ) : certificates.length === 0 ? (
        <p className="muted">
          No certificates recorded. Add each one you hold so you can see when they expire.
        </p>
      ) : (
        <ul className="task-list">
          {certificates.map((c) => (
            <li key={c.id} className="task">
              <span>
                <strong>{CERTIFICATE_KINDS[c.kind]}</strong>
                {c.number ? ` ${c.number}` : ""}
                {c.issuer ? ` · ${c.issuer}` : ""}
              </span>
              <span className={`badge certificate-${c.state.toLowerCase()}`}>
                {STATE_LABELS[c.state]}
                {c.expires_on ? ` · expires ${formatDate(c.expires_on)}` : ""}
              </span>
              {canWrite ? (
                <button
                  type="button"
                  className="button-link"
                  disabled={busy}
                  onClick={() => remove(c)}
                  aria-label={`Remove ${CERTIFICATE_KINDS[c.kind]}`}
                >
                  Remove
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {canWrite && !adding ? (
        <button
          type="button"
          className="button button-secondary"
          disabled={busy}
          onClick={() => setAdding(true)}
        >
          Add a certificate
        </button>
      ) : null}
      {canWrite && adding ? (
        <form className="form" onSubmit={add} aria-label="Add a certificate">
          <div className="field-row">
            <label>
              Certificate
              <select name="kind" required defaultValue="CERTIFICATE_OF_SURVEY">
                {Object.entries(CERTIFICATE_KINDS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Number (optional)
              <input name="number" maxLength={60} />
            </label>
          </div>
          <div className="field-row">
            <label>
              Issued by (optional)
              <input name="issuer" maxLength={200} />
            </label>
            <label>
              Issued on (optional)
              <input name="issued_on" type="date" />
            </label>
            <label>
              Expires on (optional)
              <input name="expires_on" type="date" />
            </label>
          </div>
          <div className="button-row tight">
            <button type="submit" className="button" disabled={busy}>
              Save certificate
            </button>
            <button
              type="button"
              className="button button-secondary"
              disabled={busy}
              onClick={() => setAdding(false)}
            >
              Cancel
            </button>
          </div>
        </form>
      ) : null}
    </div>
  );
}
