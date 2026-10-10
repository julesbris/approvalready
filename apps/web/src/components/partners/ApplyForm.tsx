"use client";

import type {
  AustralianState,
  MarketplaceCategoryOut,
  PartnerCredentialKind,
  PartnerOut,
  ServiceAreaKind,
} from "@approvalready/shared-types";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { useAction } from "@/components/admin/useAction";
import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";
import {
  AREA_KIND_LABELS,
  CREDENTIAL_KIND_LABELS,
  STATES,
  areaLabel,
  formatCover,
  parseCover,
} from "@/lib/partners";

export type AreaDraft = { kind: ServiceAreaKind; state: AustralianState; value: string };
export type CredentialDraft = {
  kind: PartnerCredentialKind;
  issuer: string;
  number: string;
  cover_cents: number | null;
  expires_on: string | null;
  category_keys: string[];
};

/** Add a service area: a postcode, a council area or a whole state. */
export function AreaPicker({
  busy,
  onAdd,
}: {
  busy: boolean;
  onAdd: (area: AreaDraft) => void | Promise<void>;
}) {
  const [kind, setKind] = useState<ServiceAreaKind>("LGA");
  const [state, setState] = useState<AustralianState>("QLD");
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function add() {
    const v = value.trim();
    if (kind === "POSTCODE" && !/^\d{4}$/.test(v)) {
      setError("A postcode has 4 digits.");
      return;
    }
    if (kind === "LGA" && v.length < 2) {
      setError("Enter the council area's name, for example Cairns.");
      return;
    }
    setError(null);
    await onAdd({ kind, state, value: kind === "STATE" ? state : v });
    setValue("");
  }

  return (
    <div className="form inline-form">
      <label>
        Kind of area
        <select value={kind} onChange={(e) => setKind(e.target.value as ServiceAreaKind)}>
          {Object.entries(AREA_KIND_LABELS).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label>
        State
        <select value={state} onChange={(e) => setState(e.target.value as AustralianState)}>
          {STATES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </label>
      {kind !== "STATE" ? (
        <label>
          {kind === "POSTCODE" ? "Postcode" : "Council area"}
          <input
            value={value}
            maxLength={kind === "POSTCODE" ? 4 : 120}
            inputMode={kind === "POSTCODE" ? "numeric" : "text"}
            onChange={(e) => setValue(e.target.value)}
          />
        </label>
      ) : null}
      <button type="button" className="button-secondary" disabled={busy} onClick={() => void add()}>
        Add area
      </button>
      {error ? (
        <span role="alert" className="field-error">
          {error}
        </span>
      ) : null}
    </div>
  );
}

/** Add a licence, accreditation or insurance policy, and say which categories it covers. */
export function CredentialPicker({
  busy,
  categories,
  onAdd,
}: {
  busy: boolean;
  /** The partner's chosen categories that need a credential: [key, label]. */
  categories: [string, string][];
  onAdd: (credential: CredentialDraft) => void | Promise<void>;
}) {
  const [kind, setKind] = useState<PartnerCredentialKind>("LICENCE");
  const [issuer, setIssuer] = useState("");
  const [number, setNumber] = useState("");
  const [cover, setCover] = useState("");
  const [expires, setExpires] = useState("");
  const [covers, setCovers] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const insurance = kind === "PI_INSURANCE" || kind === "PL_INSURANCE";

  async function add() {
    if (!issuer.trim() || !number.trim()) {
      setError("Enter who issued it and its number.");
      return;
    }
    const cover_cents = insurance && cover.trim() ? parseCover(cover) : null;
    if (insurance && cover.trim() && cover_cents === null) {
      setError("Enter the cover in whole dollars, for example 20000000.");
      return;
    }
    setError(null);
    await onAdd({
      kind,
      issuer: issuer.trim(),
      number: number.trim(),
      cover_cents,
      expires_on: expires || null,
      category_keys: insurance ? [] : covers.filter((k) => categories.some(([c]) => c === k)),
    });
    setIssuer("");
    setNumber("");
    setCover("");
    setExpires("");
    setCovers([]);
  }

  return (
    <div className="form">
      <div className="inline-form">
        <label>
          Kind
          <select value={kind} onChange={(e) => setKind(e.target.value as PartnerCredentialKind)}>
            {Object.entries(CREDENTIAL_KIND_LABELS).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          {insurance ? "Insurer" : "Issued by"}
          <input value={issuer} maxLength={200} onChange={(e) => setIssuer(e.target.value)} />
        </label>
        <label>
          {insurance ? "Policy number" : "Number"}
          <input value={number} maxLength={100} onChange={(e) => setNumber(e.target.value)} />
        </label>
        {insurance ? (
          <label>
            Cover ($)
            <input value={cover} inputMode="numeric" onChange={(e) => setCover(e.target.value)} />
          </label>
        ) : null}
        <label>
          Expires (if it does)
          <input type="date" value={expires} onChange={(e) => setExpires(e.target.value)} />
        </label>
      </div>
      {!insurance && categories.length > 0 ? (
        <fieldset className="plain-fieldset">
          <legend className="muted">Which of your categories does it cover?</legend>
          {categories.map(([key, label]) => (
            <label key={key}>
              <input
                type="checkbox"
                checked={covers.includes(key)}
                onChange={() =>
                  setCovers((c) => (c.includes(key) ? c.filter((x) => x !== key) : [...c, key]))
                }
              />{" "}
              {label}
            </label>
          ))}
        </fieldset>
      ) : null}
      <div className="button-row">
        <button type="button" className="button-secondary" disabled={busy} onClick={() => void add()}>
          Add credential
        </button>
      </div>
      {error ? (
        <span role="alert" className="field-error">
          {error}
        </span>
      ) : null}
    </div>
  );
}

/** Apply to become a partner: business details, categories, service areas, credentials. */
export function ApplyForm({ categories }: { categories: MarketplaceCategoryOut[] }) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [abn, setAbn] = useState("");
  const [website, setWebsite] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [description, setDescription] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);
  const [areas, setAreas] = useState<AreaDraft[]>([]);
  const [credentials, setCredentials] = useState<CredentialDraft[]>([]);
  const [declaration, setDeclaration] = useState(false);
  const { busy, error, run, setError } = useAction();

  const labels = new Map(categories.map((c) => [c.key, c.label]));
  const needsCredential = categories
    .filter((c) => c.requires_credential && chosen.includes(c.key))
    .map((c): [string, string] => [c.key, c.label]);

  function toggle(key: string) {
    setChosen((c) => (c.includes(key) ? c.filter((x) => x !== key) : [...c, key]));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (chosen.length === 0) {
      setError("Choose at least one category.");
      return;
    }
    if (areas.length === 0) {
      setError("Add at least one service area.");
      return;
    }
    const created = await run(() =>
      apiRequest<PartnerOut>("POST", "/partners/applications", {
        name,
        abn,
        website: website || null,
        phone: phone || null,
        contact_email: email || null,
        description,
        categories: chosen,
        service_areas: areas,
        credentials: credentials.map((c) => ({
          ...c,
          category_keys: c.category_keys.filter((k) => chosen.includes(k)),
        })),
        declaration,
      }),
    );
    if (!created) return;
    const switched = await apiRequest("PUT", "/auth/session/organisation", {
      organisation_id: created.organisation_id,
    });
    if (!switched.ok) {
      setError(switched.message);
      return;
    }
    router.push("/partner?applied=1");
    router.refresh();
  }

  return (
    <form method="post" className="form form-wide" onSubmit={submit}>
      <section className="panel" aria-labelledby="business-title">
        <h2 id="business-title" className="section-title">
          Your business
        </h2>
        <label>
          Business name
          <input value={name} maxLength={200} onChange={(e) => setName(e.target.value)} required />
        </label>
        <label>
          ABN
          <input
            value={abn}
            inputMode="numeric"
            maxLength={14}
            onChange={(e) => setAbn(e.target.value)}
            required
          />
        </label>
        <label>
          Website (optional)
          <input value={website} maxLength={300} onChange={(e) => setWebsite(e.target.value)} />
        </label>
        <label>
          Phone for customers (optional)
          <input value={phone} maxLength={30} onChange={(e) => setPhone(e.target.value)} />
        </label>
        <label>
          Email for customers (optional)
          <input
            type="email"
            value={email}
            maxLength={320}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <label>
          What your business does
          <textarea
            value={description}
            minLength={20}
            maxLength={2000}
            rows={4}
            onChange={(e) => setDescription(e.target.value)}
            required
          />
        </label>
      </section>

      <section className="panel" aria-labelledby="categories-title">
        <h2 id="categories-title" className="section-title">
          The work you want referrals for
        </h2>
        <p className="muted">
          We check each category before you are referred for it. Categories marked
          &quot;licence needed&quot; need a current licence or accreditation, added below.
        </p>
        <fieldset className="plain-fieldset">
          <legend className="visually-hidden">Categories</legend>
          {categories.map((c) => (
            <label key={c.key}>
              <input type="checkbox" checked={chosen.includes(c.key)} onChange={() => toggle(c.key)} />{" "}
              <strong>{c.label}</strong>
              {c.requires_credential ? <span className="badge">licence needed</span> : null}
              <br />
              <span className="muted">{c.description}</span>
            </label>
          ))}
        </fieldset>
      </section>

      <section className="panel" aria-labelledby="areas-title">
        <h2 id="areas-title" className="section-title">
          Where you work
        </h2>
        <ul className="task-list" aria-label="Your service areas">
          {areas.map((a, i) => (
            <li key={`${a.kind}-${a.state}-${a.value}`} className="task">
              <span>{areaLabel(a)}</span>
              <button
                type="button"
                className="button-link"
                onClick={() => setAreas((all) => all.filter((_, j) => j !== i))}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
        <AreaPicker busy={busy} onAdd={(a) => setAreas((all) => [...all, a])} />
      </section>

      <section className="panel" aria-labelledby="credentials-title">
        <h2 id="credentials-title" className="section-title">
          Licences and insurance
        </h2>
        <p className="muted">
          We check each one against the issuer&apos;s public register before approving the
          categories it covers.
        </p>
        <ul className="task-list" aria-label="Your credentials">
          {credentials.map((c, i) => (
            <li key={`${c.kind}-${c.number}`} className="task">
              <span>
                {CREDENTIAL_KIND_LABELS[c.kind]}: {c.issuer} {c.number}
                {c.cover_cents ? `, cover ${formatCover(c.cover_cents)}` : ""}
                {c.category_keys.length > 0
                  ? `. Covers ${c.category_keys.map((k) => labels.get(k) ?? k).join(", ")}`
                  : ""}
              </span>
              <button
                type="button"
                className="button-link"
                onClick={() => setCredentials((all) => all.filter((_, j) => j !== i))}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
        <CredentialPicker
          busy={busy}
          categories={needsCredential}
          onAdd={(c) => setCredentials((all) => [...all, c])}
        />
      </section>

      <section className="panel">
        <label>
          <input
            type="checkbox"
            checked={declaration}
            onChange={(e) => setDeclaration(e.target.checked)}
            required
          />{" "}
          The details above are true, and I can act for this business.
        </label>
        <FormError message={error} />
        <div className="button-row">
          <button type="submit" className="button" disabled={busy}>
            Send application
          </button>
        </div>
      </section>
    </form>
  );
}
