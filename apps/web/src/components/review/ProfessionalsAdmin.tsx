"use client";

import type { ProfessionalOut } from "@approvalready/shared-types";
import { useState } from "react";

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

/** Staff: check each professional's credentials, then activate (or suspend) them. */
export function ProfessionalsAdmin({ initial }: { initial: ProfessionalOut[] }) {
  const [list, setList] = useState(initial);
  const { busy, error, run } = useAction();

  const replace = (p: ProfessionalOut) =>
    setList((all) => all.map((x) => (x.id === p.id ? p : x)));

  async function check(p: ProfessionalOut, credentialId: string, status: string) {
    const notes =
      status === "REJECTED" ? window.prompt("Why isn't it accepted?") : "Checked on the register.";
    const updated = await run(() =>
      apiRequest<ProfessionalOut>(
        "POST",
        `/admin/professionals/${p.id}/credentials/${credentialId}`,
        { status, notes: notes?.trim() || null },
      ),
    );
    if (updated) replace(updated);
  }

  async function setStatus(p: ProfessionalOut, status: string) {
    const updated = await run(() =>
      apiRequest<ProfessionalOut>("POST", `/admin/professionals/${p.id}/status`, { status }),
    );
    if (updated) replace(updated);
  }

  if (list.length === 0) {
    return (
      <section className="panel empty">
        <p>No professionals have signed up yet.</p>
      </section>
    );
  }
  return (
    <>
      <FormError message={error} />
      <ul className="finding-list" aria-label="Professionals">
        {list.map((p) => (
          <li key={p.id} className="finding">
            <div className="finding-head">
              <div>
                <h2 className="finding-title">
                  {p.display_name}, {DISCIPLINE_LABELS[p.discipline]}
                </h2>
                <p className="muted">
                  {p.practice_name} · {p.email} · reviews{" "}
                  {p.services.map((s) => verticalName(s.vertical)).join(", ") || "nothing yet"}
                </p>
              </div>
              <span className="status">{PROFESSIONAL_STATUS_LABELS[p.status]}</span>
            </div>
            <ul className="task-list">
              {p.credentials.map((c) => (
                <li key={c.id} className="task">
                  <span>
                    {CREDENTIAL_KIND_LABELS[c.kind]}: {c.issuer} {c.number}
                    {c.expires_on ? `, expires ${formatDate(c.expires_on)}` : ""}
                  </span>
                  <span className="badge">
                    {c.status.toLowerCase()}
                    {c.status === "VERIFIED" && !c.current ? " (expired)" : ""}
                  </span>
                  {c.status !== "VERIFIED" ? (
                    <button
                      type="button"
                      className="button-link"
                      disabled={busy}
                      onClick={() => check(p, c.id, "VERIFIED")}
                    >
                      Mark checked
                    </button>
                  ) : null}
                  {c.status !== "REJECTED" ? (
                    <button
                      type="button"
                      className="button-link"
                      disabled={busy}
                      onClick={() => check(p, c.id, "REJECTED")}
                    >
                      Reject
                    </button>
                  ) : null}
                </li>
              ))}
            </ul>
            {p.problems.length > 0 ? <p className="muted">{p.problems.join(" ")}</p> : null}
            <div className="button-row">
              {p.status !== "ACTIVE" ? (
                <button
                  type="button"
                  className="button-secondary"
                  disabled={busy}
                  onClick={() => setStatus(p, "ACTIVE")}
                >
                  Activate
                </button>
              ) : (
                <button
                  type="button"
                  className="button-link"
                  disabled={busy}
                  onClick={() => setStatus(p, "SUSPENDED")}
                >
                  Suspend
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}
