"use client";

import type {
  CredentialKind,
  Discipline,
  ProfessionalOut,
  Vertical,
} from "@approvalready/shared-types";
import { type FormEvent, useState } from "react";

import { useAction } from "@/components/admin/useAction";
import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";
import { verticalName } from "@/lib/labels";
import { formatDate } from "@/lib/questionnaire";
import {
  CREDENTIAL_KIND_LABELS,
  DISCIPLINE_LABELS,
  PROFESSIONAL_STATUS_LABELS,
} from "@/lib/review";

const VERTICALS: Vertical[] = [
  "PLANNING",
  "VESSEL",
  "BUSINESS",
  "GRANT",
  "SELL",
  "RENT",
  "TRADE",
];

const CREDENTIAL_STATUS: Record<string, string> = {
  UNVERIFIED: "Waiting for our check",
  VERIFIED: "Checked",
  REJECTED: "Not accepted",
};

function CreateProfile({ onCreated }: { onCreated: (p: ProfessionalOut) => void }) {
  const [name, setName] = useState("");
  const [discipline, setDiscipline] = useState<Discipline>("TOWN_PLANNER");
  const [bio, setBio] = useState("");
  const { busy, error, run } = useAction();
  async function submit(event: FormEvent) {
    event.preventDefault();
    const created = await run(() =>
      apiRequest<ProfessionalOut>("POST", "/professional/profile", {
        display_name: name,
        discipline,
        bio: bio.trim() || null,
      }),
    );
    if (created) onCreated(created);
  }
  return (
    <form method="post" className="form panel" onSubmit={submit}>
      <h2 className="section-title">Set up your reviewer profile</h2>
      <p className="muted">
        Customers see your name, profession and practice. Our team checks your credentials before
        you are given any reviews.
      </p>
      <label>
        Name shown to customers
        <input value={name} maxLength={200} onChange={(e) => setName(e.target.value)} required />
      </label>
      <label>
        Profession
        <select
          value={discipline}
          onChange={(e) => setDiscipline(e.target.value as Discipline)}
        >
          {Object.entries(DISCIPLINE_LABELS).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label>
        About you (optional)
        <textarea value={bio} maxLength={1000} rows={3} onChange={(e) => setBio(e.target.value)} />
      </label>
      <FormError message={error} />
      <div className="button-row">
        <button type="submit" className="button" disabled={busy}>
          Create profile
        </button>
      </div>
    </form>
  );
}

/** A professional's own profile: credentials to be checked and the kinds of project they review. */
export function ProfileEditor({ initial }: { initial: ProfessionalOut | null }) {
  const [profile, setProfile] = useState(initial);
  const [kind, setKind] = useState<CredentialKind>("LICENCE");
  const [issuer, setIssuer] = useState("");
  const [number, setNumber] = useState("");
  const [expires, setExpires] = useState("");
  const { busy, error, run, setError } = useAction();

  if (!profile) return <CreateProfile onCreated={setProfile} />;

  async function addCredential(event: FormEvent) {
    event.preventDefault();
    const updated = await run(() =>
      apiRequest<ProfessionalOut>("POST", "/professional/profile/credentials", {
        kind,
        issuer,
        number,
        expires_on: expires || null,
      }),
    );
    if (updated) {
      setProfile(updated);
      setIssuer("");
      setNumber("");
      setExpires("");
    }
  }

  async function removeCredential(id: string) {
    const result = await apiRequest("DELETE", `/professional/profile/credentials/${id}`);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    setProfile((p) => (p ? { ...p, credentials: p.credentials.filter((c) => c.id !== id) } : p));
  }

  async function toggleService(vertical: Vertical) {
    if (!profile) return;
    const current = profile.services.map((s) => s.vertical);
    const next = current.includes(vertical)
      ? current.filter((v) => v !== vertical)
      : [...current, vertical];
    const updated = await run(() =>
      apiRequest<ProfessionalOut>("PUT", "/professional/profile/services", {
        services: next.map((v) => ({ vertical: v })),
      }),
    );
    if (updated) setProfile(updated);
  }

  return (
    <div>
      <section className="panel">
        <h2 className="section-title">
          {profile.display_name}, {DISCIPLINE_LABELS[profile.discipline]}
        </h2>
        <p>
          <span className="status">{PROFESSIONAL_STATUS_LABELS[profile.status]}</span>{" "}
          {profile.practice_name}
        </p>
        {profile.problems.length > 0 ? (
          <ul>
            {profile.problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        ) : (
          <p className="muted">You can be assigned reviews.</p>
        )}
      </section>
      <FormError message={error} />
      <section className="panel" aria-labelledby="credentials-title">
        <h2 id="credentials-title" className="section-title">
          Credentials
        </h2>
        <p className="muted">
          Licences, registrations, memberships and insurance. We check each one against the
          issuer&apos;s public register.
        </p>
        <ul className="task-list" aria-label="Your credentials">
          {profile.credentials.map((c) => (
            <li key={c.id} className="task">
              <span>
                {CREDENTIAL_KIND_LABELS[c.kind]}: {c.issuer} {c.number}
                {c.expires_on ? `, expires ${formatDate(c.expires_on)}` : ""}
              </span>
              <span className="badge">{CREDENTIAL_STATUS[c.status] ?? c.status}</span>
              {c.notes ? <span className="muted">{c.notes}</span> : null}
              <button
                type="button"
                className="button-link"
                disabled={busy}
                onClick={() => removeCredential(c.id)}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
        <form method="post" className="form inline-form" onSubmit={addCredential}>
          <label>
            Kind
            <select value={kind} onChange={(e) => setKind(e.target.value as CredentialKind)}>
              {Object.entries(CREDENTIAL_KIND_LABELS).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Issued by
            <input
              value={issuer}
              maxLength={200}
              onChange={(e) => setIssuer(e.target.value)}
              required
            />
          </label>
          <label>
            Number
            <input
              value={number}
              maxLength={100}
              onChange={(e) => setNumber(e.target.value)}
              required
            />
          </label>
          <label>
            Expires (if it does)
            <input type="date" value={expires} onChange={(e) => setExpires(e.target.value)} />
          </label>
          <button type="submit" className="button-secondary" disabled={busy}>
            Add credential
          </button>
        </form>
      </section>
      <section className="panel" aria-labelledby="services-title">
        <h2 id="services-title" className="section-title">
          What you review
        </h2>
        <fieldset className="form">
          <legend className="muted">You are only given reviews of these kinds of project.</legend>
          {VERTICALS.map((v) => (
            <label key={v}>
              <input
                type="checkbox"
                checked={profile.services.some((s) => s.vertical === v)}
                disabled={busy}
                onChange={() => toggleService(v)}
              />{" "}
              {verticalName(v)}
            </label>
          ))}
        </fieldset>
      </section>
    </div>
  );
}
