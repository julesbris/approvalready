"use client";

import type { PartnerStatus, StaffPartnerOut } from "@approvalready/shared-types";
import { useState } from "react";

import { useAction } from "@/components/admin/useAction";
import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";
import { formatDateTime, roleList } from "@/lib/labels";
import {
  CATEGORY_STATUS_LABELS,
  CREDENTIAL_KIND_LABELS,
  CREDENTIAL_STATUS_LABELS,
  PARTNER_STATUS_LABELS,
  areaLabel,
  formatCover,
} from "@/lib/partners";
import { formatDate } from "@/lib/questionnaire";

/** What staff can do next from each status (mirrors the API's transitions). */
const NEXT: Record<PartnerStatus, [PartnerStatus, string][]> = {
  APPLIED: [
    ["UNDER_REVIEW", "Start checking"],
    ["ACTIVE", "Approve"],
    ["REJECTED", "Don't approve"],
  ],
  UNDER_REVIEW: [
    ["ACTIVE", "Approve"],
    ["REJECTED", "Don't approve"],
  ],
  ACTIVE: [["SUSPENDED", "Suspend"]],
  SUSPENDED: [["ACTIVE", "Reinstate"]],
  REJECTED: [],
};

const NEEDS_REASON = new Set<PartnerStatus>(["REJECTED", "SUSPENDED"]);

/** Staff: check a partner's credentials and categories, then approve, reject or suspend. */
export function PartnerReview({ initial }: { initial: StaffPartnerOut }) {
  const [partner, setPartner] = useState(initial);
  const { busy, error, run } = useAction();
  const base = `/admin/partners/${partner.id}`;

  async function post(path: string, body: unknown) {
    const updated = await run(() => apiRequest<StaffPartnerOut>("POST", `${base}${path}`, body));
    if (updated) setPartner(updated);
  }

  function ask(question: string): string | null | undefined {
    const answer = window.prompt(question);
    return answer === null ? undefined : answer.trim() || null;
  }

  async function setStatus(status: PartnerStatus) {
    let reason: string | null = null;
    if (NEEDS_REASON.has(status)) {
      const answer = ask("Why? The partner will see this (at least 10 characters).");
      if (answer === undefined) return;
      reason = answer;
    }
    await post("/status", { status, reason });
  }

  async function checkCredential(id: string, status: string) {
    const notes =
      status === "REJECTED" ? ask("Why isn't it accepted? The partner will see this.") : null;
    if (notes === undefined) return;
    await post(`/credentials/${id}`, {
      status,
      notes: status === "VERIFIED" ? "Checked on the register." : notes,
    });
  }

  async function checkCategory(id: string, status: string) {
    const notes = status === "REJECTED" ? ask("Why not? The partner will see this.") : null;
    if (notes === undefined) return;
    await post(`/categories/${id}`, { status, notes });
  }

  const credentialName = new Map(partner.credentials.map((c) => [c.id, `${c.issuer} ${c.number}`]));

  return (
    <>
      <h1 className="page-title">
        {partner.name}{" "}
        <span className={`status status-${partner.status.toLowerCase()}`}>
          {PARTNER_STATUS_LABELS[partner.status]}
        </span>
      </h1>
      <FormError message={error} />
      <section className="panel" aria-labelledby="business-title">
        <h2 id="business-title" className="section-title">
          Business
        </h2>
        <dl className="facts">
          <dt>ABN</dt>
          <dd>
            {partner.abn ?? "missing"}{" "}
            {partner.abn ? (
              <a
                href={`https://abr.business.gov.au/ABN/View?abn=${partner.abn}`}
                target="_blank"
                rel="noopener noreferrer"
              >
                Check on ABN Lookup
              </a>
            ) : null}
          </dd>
          <dt>Website</dt>
          <dd>{partner.website ?? "none"}</dd>
          <dt>Phone</dt>
          <dd>{partner.phone ?? "none"}</dd>
          <dt>Email for customers</dt>
          <dd>{partner.contact_email ?? "none"}</dd>
          <dt>Sent</dt>
          <dd>{formatDateTime(partner.submitted_at)}</dd>
          <dt>People</dt>
          <dd>
            {partner.members
              .map((m) => `${m.display_name} <${m.email}> (${roleList(m.roles)})`)
              .join("; ")}
          </dd>
        </dl>
        <p>{partner.description}</p>
        {partner.status_reason ? (
          <p>
            <strong>Reason given:</strong> {partner.status_reason}
          </p>
        ) : null}
        <div className="button-row">
          {NEXT[partner.status].map(([status, label]) => (
            <button
              key={status}
              type="button"
              className={status === "ACTIVE" ? "button" : "button-secondary"}
              disabled={busy}
              onClick={() => void setStatus(status)}
            >
              {label}
            </button>
          ))}
        </div>
        {!partner.receiving_referrals ? (
          <p className="muted">Not receiving referrals: {partner.problems.join(" ")}</p>
        ) : (
          <p className="muted">Receiving referrals.</p>
        )}
      </section>

      <section className="panel" aria-labelledby="credentials-title">
        <h2 id="credentials-title" className="section-title">
          Licences and insurance
        </h2>
        {partner.credentials.length === 0 ? <p className="muted">None added.</p> : null}
        <ul className="task-list" aria-label="Credentials">
          {partner.credentials.map((c) => (
            <li key={c.id} className="task">
              <span>
                {CREDENTIAL_KIND_LABELS[c.kind]}: {c.issuer} {c.number}
                {c.cover_cents ? `, cover ${formatCover(c.cover_cents)}` : ""}
                {c.expires_on ? `, expires ${formatDate(c.expires_on)}` : ""}
                {c.notes ? <span className="muted"> ({c.notes})</span> : null}
              </span>
              <span className="badge">
                {CREDENTIAL_STATUS_LABELS[c.status]}
                {c.status === "VERIFIED" && !c.current ? " (expired)" : ""}
              </span>
              {c.status !== "VERIFIED" ? (
                <button
                  type="button"
                  className="button-link"
                  disabled={busy}
                  onClick={() => void checkCredential(c.id, "VERIFIED")}
                >
                  Mark checked
                </button>
              ) : null}
              {c.status !== "REJECTED" ? (
                <button
                  type="button"
                  className="button-link"
                  disabled={busy}
                  onClick={() => void checkCredential(c.id, "REJECTED")}
                >
                  Not accepted
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      </section>

      <section className="panel" aria-labelledby="categories-title">
        <h2 id="categories-title" className="section-title">
          Categories
        </h2>
        <ul className="task-list" aria-label="Categories">
          {partner.categories.map((c) => (
            <li key={c.id} className="task">
              <span>
                <strong>{c.label}</strong>
                {c.restricted ? <span className="badge">regulated advice</span> : null}
                <br />
                <span className="muted">
                  {c.requires_credential
                    ? `Needs a licence: ${
                        c.credential_id
                          ? (credentialName.get(c.credential_id) ?? "named")
                          : "none named"
                      }. `
                    : ""}
                  {c.notes ? `Note: ${c.notes}. ` : ""}
                  {c.problems.join(" ")}
                </span>
              </span>
              <span className="badge">{CATEGORY_STATUS_LABELS[c.status]}</span>
              {c.status !== "APPROVED" ? (
                <button
                  type="button"
                  className="button-link"
                  disabled={busy}
                  onClick={() => void checkCategory(c.id, "APPROVED")}
                >
                  Approve
                </button>
              ) : null}
              {c.status !== "REJECTED" ? (
                <button
                  type="button"
                  className="button-link"
                  disabled={busy}
                  onClick={() => void checkCategory(c.id, "REJECTED")}
                >
                  Don&apos;t approve
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      </section>

      <section className="panel" aria-labelledby="areas-title">
        <h2 id="areas-title" className="section-title">
          Service areas
        </h2>
        <ul className="plain-list">
          {partner.service_areas.map((a) => (
            <li key={a.id}>{areaLabel(a)}</li>
          ))}
        </ul>
      </section>

      {partner.plan ? (
        <section className="panel" aria-labelledby="plan-title">
          <h2 id="plan-title" className="section-title">
            Plan
          </h2>
          <p>
            {partner.plan.name}
            {partner.plan.status ? ` (${partner.plan.status.toLowerCase().replace("_", " ")})` : ""}
          </p>
        </section>
      ) : null}

      <section className="panel" aria-labelledby="history-title">
        <h2 id="history-title" className="section-title">
          Applications
        </h2>
        <ul className="task-list" aria-label="Applications">
          {partner.applications.map((a) => (
            <li key={a.id} className="task">
              <span>
                Sent {formatDateTime(a.submitted_at)}
                {a.reviewed_at ? `, decided ${formatDateTime(a.reviewed_at)}` : ""}
                {a.decision_notes ? `: ${a.decision_notes}` : ""}
              </span>
              <span className="badge">{a.status.toLowerCase()}</span>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
