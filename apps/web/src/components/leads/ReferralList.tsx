"use client";

import type { ReferralOut } from "@approvalready/shared-types";
import { useRouter } from "next/navigation";

import { useAction } from "@/components/admin/useAction";
import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";
import { formatDateTime } from "@/lib/labels";
import { FIELD_LABELS, LEAD_STATUS_LABELS, TIMING_LABELS } from "@/lib/leads";

/** The customer's introduction requests on a project: who accepted, and withdrawing. */
export function ReferralList({
  organisationId,
  projectId,
  referrals,
  canWrite,
}: {
  organisationId: string;
  projectId: string;
  referrals: ReferralOut[];
  canWrite: boolean;
}) {
  const router = useRouter();
  const { busy, error, run } = useAction();

  async function withdraw(id: string) {
    if (!window.confirm("Withdraw this request? Partners who haven't accepted it won't see it."))
      return;
    const done = await run(() =>
      apiRequest(
        "POST",
        `/organisations/${organisationId}/projects/${projectId}/referrals/${id}/withdraw`,
      ),
    );
    if (done !== null) router.refresh();
  }

  if (referrals.length === 0) {
    return <p className="muted">You haven&apos;t asked to be introduced to anyone yet.</p>;
  }
  return (
    <>
      <FormError message={error} />
      <ul className="finding-list">
        {referrals.map((r) => (
          <li key={r.id} className="card">
            <p className="card-title">
              Asked {formatDateTime(r.granted_at)}
              {r.withdrawn_at ? (
                <span className="status status-withdrawn"> Withdrawn</span>
              ) : null}
            </p>
            <p className="muted">
              Shared on accepting: {r.fields_released.map((f) => FIELD_LABELS[f as keyof typeof FIELD_LABELS] ?? f).join(", ")}
              . {TIMING_LABELS[r.timing]}. {r.postcode} {r.state}.
            </p>
            {r.leads.map((lead) => (
              <section key={lead.id} aria-label={lead.category_label}>
                <h3 className="card-title">
                  {lead.category_label}{" "}
                  <span className={`status status-${lead.status.toLowerCase()}`}>
                    {LEAD_STATUS_LABELS[lead.status]}
                  </span>
                </h3>
                {lead.claims.length > 0 ? (
                  <ul>
                    {lead.claims.map((c) => (
                      <li key={`${c.name}-${c.claimed_at}`}>
                        <strong>{c.name}</strong>
                        {c.is_promoted ? <span className="badge">Sponsored</span> : null} accepted{" "}
                        {formatDateTime(c.claimed_at)}.{" "}
                        {[c.phone, c.contact_email, c.website].filter(Boolean).join(" · ")}
                      </li>
                    ))}
                  </ul>
                ) : lead.status === "OPEN" ? (
                  <p className="muted">
                    {lead.offered_count > 0
                      ? "Offered to partners in your area. We'll tell you when one accepts."
                      : "No partner covers this area yet. We keep looking until the request ends."}
                  </p>
                ) : (
                  <p className="muted">No partner accepted this request.</p>
                )}
                <p className="muted">
                  {lead.claimed_count} of {lead.max_claims} accepted
                  {lead.status === "OPEN" ? `. Ends ${formatDateTime(lead.expires_at)}` : ""}.
                </p>
              </section>
            ))}
            {canWrite && !r.withdrawn_at && r.leads.some((l) => l.status === "OPEN") ? (
              <div className="button-row">
                <button
                  type="button"
                  className="button-secondary"
                  disabled={busy}
                  onClick={() => void withdraw(r.id)}
                >
                  Withdraw this request
                </button>
              </div>
            ) : null}
          </li>
        ))}
      </ul>
      <p className="muted">
        Partners are checked by us and ranked on area, specialisation, insurance, how quickly
        they reply and how busy they are. They don&apos;t pay to rank higher. We don&apos;t
        recommend or guarantee any partner.
      </p>
    </>
  );
}
