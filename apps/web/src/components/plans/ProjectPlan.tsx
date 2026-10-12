"use client";

import type {
  DocumentOut,
  PlanHelpOut,
  PlanSectionOut,
  PlanStepOut,
  PlanStepUpdate,
  ProjectPlanOut,
  SuggestedPartnerOut,
} from "@approvalready/shared-types";
import Link from "next/link";
import { type FormEvent, useState } from "react";

import { useAction } from "@/components/admin/useAction";
import { FormError, FormNotice } from "@/components/auth/FormStatus";
import { phoneHref } from "@/lib/approvalGuides";
import { apiRequest } from "@/lib/client-api";
import { uploadDocument } from "@/lib/documents";
import {
  dropStep,
  dueLabel,
  introductionHref,
  isOverdue,
  KIND_LABELS,
  putStep,
  SECTION_STATE_CLASSES,
  SECTION_STATE_LABELS,
  sectionState,
  todayIso,
  websiteHref,
} from "@/lib/plans";
import { formatDate } from "@/lib/questionnaire";

type Props = {
  organisationId: string;
  projectId: string;
  /** The latest assessment, for asking partners for an introduction. */
  assessmentId: string | null;
  plan: ProjectPlanOut;
  documents: DocumentOut[];
  canWrite: boolean;
};

function External({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a href={href} rel="noopener noreferrer" target="_blank">
      {children}
    </a>
  );
}

/** The project plan: progress, a timeline of its parts, and every step to tick off, with
 * dates, owners, notes, files, and partners to call for each part. */
export function ProjectPlan(props: Props) {
  const { organisationId, projectId, canWrite } = props;
  const [plan, setPlan] = useState(props.plan);
  const [documents, setDocuments] = useState(props.documents);
  const [notice, setNotice] = useState<string | null>(null);
  const { busy, error, run } = useAction();
  const base = `/organisations/${organisationId}/projects/${projectId}/plan`;
  const today = todayIso();
  const progress = plan.progress;
  const next = plan.sections.flatMap((s) => s.steps).find((s) => s.id === progress?.next_item_id);

  async function update(step: PlanStepOut, changes: PlanStepUpdate) {
    const saved = await run(() =>
      apiRequest<PlanStepOut>("PATCH", `${base}/steps/${step.id}`, changes),
    );
    if (saved) setPlan((p) => putStep(p, saved));
    return saved;
  }

  async function remove(step: PlanStepOut) {
    const done = await run(() => apiRequest<null>("DELETE", `${base}/steps/${step.id}`));
    if (done !== null) setPlan((p) => dropStep(p, step.id));
  }

  async function followUp(partner: SuggestedPartnerOut, section: PlanSectionOut) {
    const saved = await run(() =>
      apiRequest<PlanStepOut>("POST", `${base}/follow-ups`, {
        partner_id: partner.id,
        section_key: section.key,
      }),
    );
    if (saved) {
      setPlan((p) => putStep(p, saved));
      setNotice(
        `Added "${saved.title}" for ${saved.due_on ? formatDate(saved.due_on) : "soon"}. ` +
          "We'll email you a reminder that morning.",
      );
    }
  }

  async function refresh() {
    const fresh = await run(() => apiRequest<ProjectPlanOut>("POST", `${base}/refresh`));
    if (fresh) {
      const before = plan.sections.reduce((n, s) => n + s.steps.length, 0);
      const after = fresh.sections.reduce((n, s) => n + s.steps.length, 0);
      setPlan(fresh);
      setNotice(
        after > before
          ? `Added ${after - before} new step${after - before === 1 ? "" : "s"} from your latest assessment.`
          : "Your plan already has everything from your latest assessment.",
      );
    }
  }

  async function upload(file: File): Promise<DocumentOut | null> {
    const doc = await run(() => uploadDocument(organisationId, projectId, file));
    if (doc) setDocuments((d) => [doc, ...d]);
    return doc;
  }

  return (
    <div className="plan">
      <section className="panel plan-summary" aria-labelledby="plan-title">
        <div className="plan-summary-head">
          <div>
            <h1 id="plan-title" className="page-title">
              Project plan
            </h1>
            <p className="muted">
              Started {plan.starts_on ? formatDate(plan.starts_on) : "today"}
              {progress?.finish_on
                ? ` · on track to finish by ${formatDate(progress.finish_on)}`
                : ""}
            </p>
          </div>
          <div className="button-row tight no-print">
            <button
              type="button"
              className="button button-secondary"
              onClick={() => window.print()}
            >
              Print
            </button>
            {canWrite ? (
              <button
                type="button"
                className="button button-secondary"
                disabled={busy}
                onClick={refresh}
              >
                Update from latest assessment
              </button>
            ) : null}
          </div>
        </div>
        {progress ? (
          <>
            <div
              className="plan-meter"
              role="progressbar"
              aria-label="Steps done"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={progress.percent}
            >
              <span style={{ width: `${progress.percent}%` }} />
            </div>
            <p className="plan-stats">
              <strong>
                {progress.done} of {progress.total} steps done ({progress.percent}%)
              </strong>
              {progress.overdue ? (
                <span className="status status-failed">{progress.overdue} overdue</span>
              ) : null}
              {progress.due_this_week ? (
                <span className="status status-in_progress">
                  {progress.due_this_week} due this week
                </span>
              ) : null}
            </p>
            {next ? (
              <p>
                <strong>Next:</strong> <a href={`#step-${next.id}`}>{next.title}</a>
                {next.due_on ? (
                  <span className="muted"> · {dueLabel(next.due_on, today)}</span>
                ) : null}
              </p>
            ) : null}
          </>
        ) : null}
        <FormError message={error} />
        {notice ? <FormNotice>{notice}</FormNotice> : null}
      </section>

      <section className="panel" aria-labelledby="timeline-title">
        <h2 id="timeline-title" className="section-title">
          Timeline
        </h2>
        <ol className="plan-timeline">
          {plan.sections.map((s, i) => {
            const state = sectionState(s, today);
            return (
              <li key={s.key}>
                <span className="guide-number" aria-hidden="true">
                  {i + 1}
                </span>
                <div>
                  <a href={`#part-${i + 1}`} className="plan-timeline-title">
                    {s.title}
                  </a>
                  <div className="muted">
                    {s.starts_on && s.ends_on
                      ? `${formatDate(s.starts_on)} to ${formatDate(s.ends_on)} · `
                      : ""}
                    {s.done} of {s.total} done
                  </div>
                </div>
                <span className={`status ${SECTION_STATE_CLASSES[state]}`}>
                  {SECTION_STATE_LABELS[state]}
                </span>
              </li>
            );
          })}
        </ol>
      </section>

      {plan.sections.map((s, i) => (
        <PlanSection
          key={s.key}
          number={i + 1}
          section={s}
          projectId={projectId}
          assessmentId={props.assessmentId}
          documents={documents}
          canWrite={canWrite}
          busy={busy}
          today={today}
          onUpdate={update}
          onRemove={remove}
          onFollowUp={followUp}
          onUpload={upload}
        />
      ))}

      {canWrite ? (
        <AddStep
          sections={plan.sections}
          onAdd={async (body) => {
            const saved = await run(() => apiRequest<PlanStepOut>("POST", `${base}/steps`, body));
            if (saved) setPlan((p) => putStep(p, saved));
            return saved !== null;
          }}
          busy={busy}
        />
      ) : null}
    </div>
  );
}

type SectionProps = {
  number: number;
  section: PlanSectionOut;
  projectId: string;
  assessmentId: string | null;
  documents: DocumentOut[];
  canWrite: boolean;
  busy: boolean;
  today: string;
  onUpdate: (step: PlanStepOut, changes: PlanStepUpdate) => Promise<PlanStepOut | null>;
  onRemove: (step: PlanStepOut) => Promise<void>;
  onFollowUp: (partner: SuggestedPartnerOut, section: PlanSectionOut) => Promise<void>;
  onUpload: (file: File) => Promise<DocumentOut | null>;
};

function PlanSection(props: SectionProps) {
  const { section: s, number, today } = props;
  const state = sectionState(s, today);
  return (
    <section
      className="panel plan-part"
      id={`part-${number}`}
      aria-labelledby={`part-${number}-title`}
    >
      <div className="plan-part-head">
        <span className="guide-number" aria-hidden="true">
          {number}
        </span>
        <div className="plan-part-heading">
          <h2 id={`part-${number}-title`} className="section-title">
            {s.title}
          </h2>
          <p className="muted">
            {[s.authority, s.certainty_label].filter(Boolean).join(" · ")}
            {s.starts_on && s.ends_on
              ? `${s.authority || s.certainty_label ? " · " : ""}${formatDate(s.starts_on)} to ${formatDate(s.ends_on)}`
              : ""}
          </p>
        </div>
        <span className={`status ${SECTION_STATE_CLASSES[state]}`}>
          {s.done} of {s.total} · {SECTION_STATE_LABELS[state]}
        </span>
      </div>
      {s.summary ? <p>{s.summary}</p> : null}
      {s.forms.length > 0 ? (
        <div className="plan-forms">
          <p className="finding-label">Forms</p>
          <ul className="guide-list form-list">
            {s.forms.map((f) => (
              <li key={f.url}>
                <a href={f.url} rel="noopener noreferrer" target="_blank">
                  {f.label}
                </a>
                <span className="muted"> · {f.publisher}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {s.timeframe || s.cost_summary ? (
        <dl className="review-list">
          {s.timeframe ? (
            <div>
              <dt>How long</dt>
              <dd>{s.timeframe}</dd>
            </div>
          ) : null}
          {s.cost_summary ? (
            <div>
              <dt>What it costs</dt>
              <dd>{s.cost_summary}</dd>
            </div>
          ) : null}
        </dl>
      ) : null}

      {s.help.length > 0 ? (
        <div className="plan-help">
          <h3 className="plan-subtitle">Who to call</h3>
          {s.help.map((h) => (
            <HelpBlock key={h.key} help={h} {...props} />
          ))}
        </div>
      ) : null}

      <ol className="plan-steps">
        {s.steps.map((step) => (
          <PlanStep key={step.id} step={step} {...props} />
        ))}
      </ol>

      <SectionReference section={s} />
    </section>
  );
}

function HelpBlock(props: SectionProps & { help: PlanHelpOut }) {
  const { help, section, projectId, assessmentId, canWrite, busy } = props;
  return (
    <div className="plan-help-group">
      <p className="plan-help-label">
        <strong>{help.label}</strong>
        {help.introduction_open ? (
          <span className="status status-in_progress">Introduction requested</span>
        ) : null}
      </p>
      {help.partners.length === 0 ? (
        <p className="muted">
          No checked partners in your area for this yet.
          {canWrite && assessmentId && !help.introduction_open ? (
            <>
              {" "}
              <Link href={introductionHref(projectId, assessmentId, help.key)}>
                Ask us to find one
              </Link>
              .
            </>
          ) : null}
        </p>
      ) : (
        <ul className="plan-partners">
          {help.partners.map((p) => (
            <li key={p.id} className="plan-partner">
              <div className="plan-partner-name">
                <strong>{p.name}</strong>
                {p.introduced ? (
                  <span className="status status-accepted">Introduced</span>
                ) : (
                  <span className="status status-verified">Checked partner</span>
                )}
              </div>
              <p className="muted">{p.why}</p>
              {p.description ? <p className="plan-partner-about">{p.description}</p> : null}
              <p className="plan-partner-contact">
                {p.phone ? <a href={phoneHref(p.phone) ?? undefined}>{p.phone}</a> : null}
                {p.email ? <a href={`mailto:${p.email}`}>{p.email}</a> : null}
                {p.website ? <External href={websiteHref(p.website)}>Website</External> : null}
              </p>
              {canWrite ? (
                <div className="button-row tight">
                  <button
                    type="button"
                    className="button button-secondary"
                    disabled={busy}
                    onClick={() => props.onFollowUp(p, section)}
                  >
                    Add a follow-up call
                  </button>
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {help.partners.length > 0 && canWrite && assessmentId && !help.introduction_open ? (
        <p className="hint">
          Prefer they call you?{" "}
          <Link href={introductionHref(projectId, assessmentId, help.key)}>
            Ask for introductions
          </Link>{" "}
          and partners who take it on contact you. Your details go only to the partners you agree
          to.
        </p>
      ) : null}
    </div>
  );
}

function PlanStep(props: SectionProps & { step: PlanStepOut }) {
  const { step, canWrite, busy, today, documents } = props;
  const [owner, setOwner] = useState(step.owner ?? "");
  const [note, setNote] = useState(step.note ?? "");
  const [title, setTitle] = useState(step.title);
  const done = step.status === "DONE";
  const skipped = step.status === "NOT_APPLICABLE";
  const overdue = isOverdue(step, today);
  const attached = new Set(step.documents.map((d) => d.id));
  const attachable = documents.filter((d) => d.scan_status === "CLEAN" && !attached.has(d.id));
  const checkboxId = `step-${step.id}-done`;

  return (
    <li
      id={`step-${step.id}`}
      className={`plan-step${done ? " is-done" : ""}${skipped ? " is-skipped" : ""}`}
    >
      <div className="plan-step-main">
        <input
          id={checkboxId}
          type="checkbox"
          checked={done}
          disabled={!canWrite || busy || skipped}
          onChange={(e) => props.onUpdate(step, { status: e.target.checked ? "DONE" : "OPEN" })}
        />
        <div className="plan-step-body">
          <label htmlFor={checkboxId} className="plan-step-title">
            {step.title}
          </label>
          <div className="plan-step-meta">
            <span className="badge">{KIND_LABELS[step.kind] ?? step.kind}</span>
            {skipped ? <span className="muted">Doesn&apos;t apply</span> : null}
            {step.due_on && !done && !skipped ? (
              <span className={overdue ? "plan-overdue" : "muted"}>
                {dueLabel(step.due_on, today)}
              </span>
            ) : null}
            {step.owner ? <span className="muted">Owner: {step.owner}</span> : null}
            {step.timeframe ? <span className="muted">Time: {step.timeframe}</span> : null}
            {step.cost ? <span className="muted">Cost: {step.cost}</span> : null}
          </div>
          {step.detail ? <p className="plan-step-detail">{step.detail}</p> : null}
          {step.partner ? (
            <p className="plan-partner-contact">
              {step.partner.phone ? (
                <a href={phoneHref(step.partner.phone) ?? undefined}>{step.partner.phone}</a>
              ) : null}
              {step.partner.email ? (
                <a href={`mailto:${step.partner.email}`}>{step.partner.email}</a>
              ) : null}
            </p>
          ) : null}
          {step.link_url ? (
            <p className="plan-step-link">
              <External href={step.link_url}>
                {step.link_label ?? "Open the official page"}
              </External>
            </p>
          ) : step.link_label ? (
            <p className="muted">{step.link_label}</p>
          ) : null}
          {step.documents.length > 0 ? (
            <p className="plan-step-files">
              Files:{" "}
              {step.documents.map((d, i) => (
                <span key={d.id}>
                  {i > 0 ? ", " : ""}
                  {d.filename}
                </span>
              ))}
            </p>
          ) : null}
          {step.note ? <p className="plan-step-note">Note: {step.note}</p> : null}

          {canWrite ? (
            <details className="plan-step-edit no-print">
              <summary>Date, owner, notes and files</summary>
              <div className="form plan-step-form">
                {step.editable ? (
                  <label>
                    Step
                    <input
                      value={title}
                      maxLength={600}
                      onChange={(e) => setTitle(e.target.value)}
                    />
                  </label>
                ) : null}
                <label>
                  Due date
                  <input
                    type="date"
                    value={step.due_on ?? ""}
                    onChange={(e) => props.onUpdate(step, { due_on: e.target.value || null })}
                  />
                </label>
                <label>
                  Who&apos;s doing it
                  <input
                    value={owner}
                    maxLength={120}
                    placeholder="You, your builder, your planner..."
                    onChange={(e) => setOwner(e.target.value)}
                  />
                </label>
                <label>
                  Notes
                  <textarea
                    value={note}
                    maxLength={2000}
                    onChange={(e) => setNote(e.target.value)}
                  />
                </label>
                <div className="button-row tight">
                  <button
                    type="button"
                    className="button"
                    disabled={busy}
                    onClick={() =>
                      props.onUpdate(step, {
                        owner: owner.trim() || null,
                        note: note.trim() || null,
                        ...(step.editable && title.trim() ? { title: title.trim() } : {}),
                      })
                    }
                  >
                    Save
                  </button>
                  <button
                    type="button"
                    className="button button-secondary"
                    disabled={busy}
                    onClick={() =>
                      props.onUpdate(step, { status: skipped ? "OPEN" : "NOT_APPLICABLE" })
                    }
                  >
                    {skipped ? "It applies after all" : "Doesn't apply to me"}
                  </button>
                  {step.editable ? (
                    <button
                      type="button"
                      className="button button-secondary"
                      disabled={busy}
                      onClick={() => props.onRemove(step)}
                    >
                      Remove
                    </button>
                  ) : null}
                </div>
                {attachable.length > 0 ? (
                  <label>
                    Attach a file you uploaded
                    <select
                      value=""
                      onChange={(e) =>
                        e.target.value &&
                        props.onUpdate(step, {
                          document_ids: [...step.documents.map((d) => d.id), e.target.value],
                        })
                      }
                    >
                      <option value="">Choose a file</option>
                      {attachable.map((d) => (
                        <option key={d.id} value={d.id}>
                          {d.filename}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}
                <label>
                  Upload a file for this step
                  <input
                    type="file"
                    onChange={async (e) => {
                      const file = e.target.files?.[0];
                      e.target.value = "";
                      if (!file) return;
                      const doc = await props.onUpload(file);
                      if (doc && doc.scan_status === "CLEAN") {
                        await props.onUpdate(step, {
                          document_ids: [...step.documents.map((d) => d.id), doc.id],
                        });
                      }
                    }}
                  />
                </label>
                <p className="hint">
                  Files are virus-checked first; a file still being checked can be attached from the
                  list once it&apos;s ready.
                </p>
              </div>
            </details>
          ) : null}
        </div>
      </div>
    </li>
  );
}

function SectionReference({ section: s }: { section: PlanSectionOut }) {
  if (!s.fees.length && !s.contacts.length && !s.watch_out.length && !s.sources.length) return null;
  return (
    <details className="guide-more">
      <summary>Fees, contacts, what to watch out for and sources</summary>
      {s.fees.length > 0 ? (
        <table className="guide-fees">
          <thead>
            <tr>
              <th scope="col">Fee</th>
              <th scope="col" className="guide-amount">
                Amount
              </th>
            </tr>
          </thead>
          <tbody>
            {s.fees.map((f, i) => (
              <tr key={i}>
                <td>
                  {f.label}
                  {f.note ? <div className="muted">{f.note}</div> : null}
                </td>
                <td className="guide-amount">{f.amount}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {s.contacts.length > 0 ? (
        <ul className="guide-contacts">
          {s.contacts.map((c, i) => (
            <li key={i}>
              <strong>{c.name}</strong>
              {c.phone ? (
                <>
                  {" "}
                  <a href={phoneHref(c.phone) ?? undefined}>{c.phone}</a>
                </>
              ) : null}
              {c.email ? (
                <>
                  {" "}
                  <a href={`mailto:${c.email}`}>{c.email}</a>
                </>
              ) : null}
              {c.url ? (
                <>
                  {" "}
                  <External href={c.url}>Website</External>
                </>
              ) : null}
              {c.hours ? <div className="muted">{c.hours}</div> : null}
              {c.note ? <div className="muted">{c.note}</div> : null}
            </li>
          ))}
        </ul>
      ) : null}
      {s.watch_out.length > 0 ? (
        <>
          <h3 className="plan-subtitle">Watch out for</h3>
          <ul className="guide-list">
            {s.watch_out.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </>
      ) : null}
      {s.sources.length > 0 ? (
        <p className="muted">
          {s.checked_on
            ? `Gathered from official websites on ${formatDate(s.checked_on)}${s.verified ? " and checked by our team" : ", not yet checked by our team"}. `
            : ""}
          Sources:{" "}
          {s.sources.map((src, i) => (
            <span key={i}>
              {i > 0 ? "; " : ""}
              {src.url ? <External href={src.url}>{src.title}</External> : src.title}
            </span>
          ))}
        </p>
      ) : null}
    </details>
  );
}

function AddStep({
  sections,
  onAdd,
  busy,
}: {
  sections: PlanSectionOut[];
  onAdd: (body: {
    title: string;
    due_on: string | null;
    section_key: string | null;
    owner: string | null;
  }) => Promise<boolean>;
  busy: boolean;
}) {
  const [title, setTitle] = useState("");
  const [dueOn, setDueOn] = useState("");
  const [owner, setOwner] = useState("");
  const [sectionKey, setSectionKey] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    const ok = await onAdd({
      title: title.trim(),
      due_on: dueOn || null,
      section_key: sectionKey || null,
      owner: owner.trim() || null,
    });
    if (ok) {
      setTitle("");
      setDueOn("");
      setOwner("");
    }
  }

  return (
    <section className="panel no-print" aria-labelledby="add-step-title">
      <h2 id="add-step-title" className="section-title">
        Add your own step
      </h2>
      <form className="form" method="post" onSubmit={submit}>
        <label>
          What needs doing
          <input
            value={title}
            maxLength={600}
            required
            placeholder="Get three quotes for the slab"
            onChange={(e) => setTitle(e.target.value)}
          />
        </label>
        <label>
          Part of the plan
          <select value={sectionKey} onChange={(e) => setSectionKey(e.target.value)}>
            <option value="">Your own steps and follow-ups</option>
            {sections
              .filter((s) => s.key !== "own")
              .map((s) => (
                <option key={s.key} value={s.key}>
                  {s.title}
                </option>
              ))}
          </select>
        </label>
        <label>
          Due date
          <input type="date" value={dueOn} onChange={(e) => setDueOn(e.target.value)} />
        </label>
        <label>
          Who&apos;s doing it
          <input
            value={owner}
            maxLength={120}
            placeholder="You"
            onChange={(e) => setOwner(e.target.value)}
          />
        </label>
        <div>
          <button type="submit" className="button" disabled={busy || !title.trim()}>
            Add step
          </button>
        </div>
      </form>
    </section>
  );
}
