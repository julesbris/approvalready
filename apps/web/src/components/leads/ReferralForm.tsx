"use client";

import type {
  AustralianState,
  ReferralIn,
  ReferralOptionsOut,
  ReferralOut,
  ReleasableField,
  Timing,
} from "@approvalready/shared-types";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { useAction } from "@/components/admin/useAction";
import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";
import { FIELD_LABELS, RELEASABLE_FIELDS, TIMING_LABELS } from "@/lib/leads";
import { STATES } from "@/lib/partners";

/** The customer asks to be introduced to partners: what work, how many partners, which
 * contact details they share, and their agreement to the consent text shown. */
export function ReferralForm({
  organisationId,
  projectId,
  options,
}: {
  organisationId: string;
  projectId: string;
  options: ReferralOptionsOut;
}) {
  const router = useRouter();
  const { busy, error, run } = useAction();
  const available = options.categories.filter((c) => !c.open_request);
  const [categories, setCategories] = useState<string[]>(
    available.length === 1 ? [available[0]!.key] : [],
  );
  const [maxProviders, setMaxProviders] = useState(Math.min(2, options.max_providers));
  const [fields, setFields] = useState<ReleasableField[]>(["name", "phone"]);
  const [contact, setContact] = useState<Record<ReleasableField, string>>({
    name: options.contact.name ?? "",
    email: options.contact.email ?? "",
    phone: options.contact.phone ?? "",
    site_address: options.contact.site_address ?? "",
  });
  const [suburb, setSuburb] = useState(options.location.suburb ?? "");
  const [lga, setLga] = useState(options.location.lga ?? "");
  const [state, setState] = useState<AustralianState>(
    (options.location.state as AustralianState | null) ?? "QLD",
  );
  const [postcode, setPostcode] = useState(options.location.postcode ?? "");
  const [timing, setTiming] = useState<Timing>("WITHIN_3_MONTHS");
  const [summary, setSummary] = useState("");
  const [agreed, setAgreed] = useState(false);

  if (!options.consent) {
    return <p className="muted">Introductions to partners aren&apos;t available yet.</p>;
  }
  const consent = options.consent;

  function toggle<T>(list: T[], value: T): T[] {
    return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const body: ReferralIn = {
      assessment_id: options.assessment_id,
      consent_text_version_id: consent.id,
      agreed,
      categories,
      max_providers: maxProviders,
      fields_released: fields,
      contact: Object.fromEntries(
        fields.map((f) => [f, contact[f].trim() || null]),
      ) as ReferralIn["contact"],
      location: { suburb: suburb.trim() || null, lga: lga.trim() || null, state, postcode },
      timing,
      summary: summary.trim() || null,
    };
    const done = await run(() =>
      apiRequest<ReferralOut[]>(
        "POST",
        `/organisations/${organisationId}/projects/${projectId}/referrals`,
        body,
      ),
    );
    if (done !== null) {
      router.push(`/projects/${projectId}/referrals?sent=1`);
      router.refresh();
    }
  }

  if (available.length === 0) {
    return (
      <p className="muted">
        You already have introductions in progress for every kind of help this assessment found.
      </p>
    );
  }

  return (
    <form method="post" className="form" onSubmit={(e) => void submit(e)}>
      <section className="panel" aria-labelledby="work-title">
        <h2 id="work-title" className="section-title">
          Who you&apos;d like to hear from
        </h2>
        <fieldset className="plain-fieldset">
          <legend className="visually-hidden">Kinds of work</legend>
          {available.map((c) => (
            <label key={c.key}>
              <input
                type="checkbox"
                checked={categories.includes(c.key)}
                onChange={() => setCategories((all) => toggle(all, c.key))}
              />{" "}
              <strong>{c.label}</strong>
              {c.description ? (
                <>
                  <br />
                  <span className="muted">{c.description}</span>
                </>
              ) : null}
            </label>
          ))}
        </fieldset>
        <label>
          How many partners may contact you (for each kind of work)
          <select value={maxProviders} onChange={(e) => setMaxProviders(Number(e.target.value))}>
            {Array.from({ length: options.max_providers }, (_, i) => i + 1).map((n) => (
              <option key={n} value={n}>
                {n === 1 ? "1 partner" : `Up to ${n} partners`}
              </option>
            ))}
          </select>
        </label>
        <label>
          When do you want to start?
          <select value={timing} onChange={(e) => setTiming(e.target.value as Timing)}>
            {Object.entries(TIMING_LABELS).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Describe the job in a sentence or two (optional)
          <textarea
            value={summary}
            maxLength={600}
            rows={3}
            onChange={(e) => setSummary(e.target.value)}
          />
          <span className="muted">
            Partners read this before they accept. Don&apos;t include your name or contact
            details.
          </span>
        </label>
      </section>

      <section className="panel" aria-labelledby="where-title">
        <h2 id="where-title" className="section-title">
          Where the work is
        </h2>
        <p className="muted">Partners see this area before they accept, not your address.</p>
        <label>
          Suburb (optional)
          <input value={suburb} maxLength={100} onChange={(e) => setSuburb(e.target.value)} />
        </label>
        <label>
          Council area (optional)
          <input value={lga} maxLength={120} onChange={(e) => setLga(e.target.value)} />
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
        <label>
          Postcode
          <input
            value={postcode}
            maxLength={4}
            inputMode="numeric"
            pattern="\d{4}"
            required
            onChange={(e) => setPostcode(e.target.value)}
          />
        </label>
      </section>

      <section className="panel" aria-labelledby="share-title">
        <h2 id="share-title" className="section-title">
          What partners get when they accept
        </h2>
        <p className="muted">Tick the details you&apos;re happy to share. Nothing else is shared.</p>
        {RELEASABLE_FIELDS.map((f) => (
          <div key={f} className="field-row">
            <label>
              <input
                type="checkbox"
                checked={fields.includes(f)}
                onChange={() => setFields((all) => toggle(all, f))}
              />{" "}
              {FIELD_LABELS[f]}
            </label>
            {fields.includes(f) ? (
              <input
                aria-label={FIELD_LABELS[f]}
                type={f === "email" ? "email" : "text"}
                value={contact[f]}
                maxLength={f === "site_address" ? 300 : 200}
                required
                onChange={(e) => setContact((c) => ({ ...c, [f]: e.target.value }))}
              />
            ) : null}
          </div>
        ))}
      </section>

      <section className="panel" aria-labelledby="consent-title">
        <h2 id="consent-title" className="section-title">
          {consent.title}
        </h2>
        <div className="consent-text">
          {consent.body.split("\n\n").map((para) => (
            <p key={para}>{para}</p>
          ))}
        </div>
        <p className="muted">Consent wording version {consent.version}.</p>
        <label>
          <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />{" "}
          I agree. Introduce me to partners as described above.
        </label>
        <FormError message={error} />
        <div className="button-row">
          <button
            type="submit"
            className="button"
            disabled={busy || !agreed || categories.length === 0 || fields.length === 0}
          >
            Introduce me
          </button>
        </div>
      </section>
    </form>
  );
}
