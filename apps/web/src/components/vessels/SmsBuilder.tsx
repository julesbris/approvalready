"use client";

import type { SmsElementOut, SmsOut } from "@approvalready/shared-types";
import Link from "next/link";
import { useState } from "react";

import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";
import { formatDateTime } from "@/lib/labels";

type Props = {
  organisationId: string;
  projectId: string;
  latestAssessmentId: string | null;
  sms: SmsOut;
  canWrite: boolean;
};

function texts(sms: SmsOut): Record<string, string> {
  return Object.fromEntries(
    sms.sections.flatMap((s) => s.elements.map((e) => [e.key, e.text ?? ""] as const)),
  );
}

/** Write a safety management system part by part, under Marine Order 504's headings. Each
 * section saves on its own; nothing is generated for the customer except an optional starting
 * text from their own vessel details. */
export function SmsBuilder({
  organisationId,
  projectId,
  latestAssessmentId,
  canWrite,
  ...props
}: Props) {
  const [sms, setSms] = useState(props.sms);
  const [draft, setDraft] = useState<Record<string, string>>(() => texts(props.sms));
  const [saving, setSaving] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const url = `/organisations/${organisationId}/projects/${projectId}/sms`;

  function changed(elements: SmsElementOut[]): boolean {
    return elements.some((e) => (draft[e.key] ?? "") !== (e.text ?? ""));
  }

  async function save(sectionKey: string, elements: SmsElementOut[]) {
    setSaving(sectionKey);
    setSaved(null);
    setError(null);
    const content = Object.fromEntries(
      elements
        .filter((e) => (draft[e.key] ?? "") !== (e.text ?? ""))
        .map((e) => [e.key, draft[e.key]?.trim() ? draft[e.key] : null]),
    );
    const result = await apiRequest<SmsOut>("PUT", url, { content });
    setSaving(null);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    setSms(result.data);
    setDraft((d) => ({ ...d, ...texts(result.data) }));
    setSaved(sectionKey);
  }

  return (
    <div className="workspace">
      <section className="page-head" aria-labelledby="sms-title">
        <div>
          <h1 id="sms-title" className="page-title">
            {sms.title}
          </h1>
          <p className="muted">
            {sms.written} of {sms.required} required parts written
            {sms.saved_at ? ` · Last saved ${formatDateTime(sms.saved_at)}` : ""}
          </p>
        </div>
      </section>
      <p>{sms.description}</p>
      <p className="notice">{sms.disclaimer}</p>
      {sms.outdated_structure ? (
        <p className="notice">
          The headings have been updated since you last saved. Check each part still says what
          you need.
        </p>
      ) : null}
      <p className="hint">
        Based on:{" "}
        {sms.sources.map((s, i) => (
          <span key={s.url}>
            {i > 0 ? "; " : null}
            <a href={s.url} target="_blank" rel="noreferrer">
              {s.title}
            </a>{" "}
            ({s.organisation})
          </span>
        ))}
      </p>
      <FormError message={error} />

      {sms.sections.map((section) => (
        <section key={section.key} className="panel" aria-labelledby={`sms-${section.key}`}>
          <h2 id={`sms-${section.key}`} className="section-title">
            {section.title}
          </h2>
          <form
            className="form"
            onSubmit={(event) => {
              event.preventDefault();
              save(section.key, section.elements);
            }}
          >
            {section.elements.map((e) => (
              <div key={e.key} className="sms-field">
                <label htmlFor={`sms-el-${e.key}`}>
                  {e.title}
                  {e.required ? null : <span className="muted"> (if it applies)</span>}
                </label>
                <p className="hint">{e.guidance}</p>
                {e.suggestion && !draft[e.key] && canWrite ? (
                  <p className="hint">
                    <button
                      type="button"
                      className="button-link"
                      onClick={() => setDraft((d) => ({ ...d, [e.key]: e.suggestion ?? "" }))}
                    >
                      Start from your vessel&apos;s details
                    </button>
                  </p>
                ) : null}
                <textarea
                  id={`sms-el-${e.key}`}
                  rows={6}
                  maxLength={20000}
                  readOnly={!canWrite}
                  value={draft[e.key] ?? ""}
                  onChange={(ev) => setDraft((d) => ({ ...d, [e.key]: ev.target.value }))}
                />
              </div>
            ))}
            {canWrite ? (
              <div className="button-row tight">
                <button
                  type="submit"
                  className="button"
                  disabled={saving !== null || !changed(section.elements)}
                >
                  {saving === section.key ? "Saving…" : "Save this section"}
                </button>
                {saved === section.key ? <span className="muted">Saved.</span> : null}
              </div>
            ) : null}
          </form>
        </section>
      ))}

      <section className="panel" aria-labelledby="sms-download-title">
        <h2 id="sms-download-title" className="section-title">
          Download your SMS
        </h2>
        {latestAssessmentId ? (
          <p>
            Make a PDF, Word or HTML copy from{" "}
            <Link href={`/projects/${projectId}/assessments/${latestAssessmentId}`}>
              your latest assessment
            </Link>
            , so it carries the vessel details and sources it was written for.
          </p>
        ) : (
          <p className="muted">
            Run an assessment on the project first; the downloadable SMS includes the vessel
            details and sources from it.
          </p>
        )}
      </section>
    </div>
  );
}
