"use client";

import type {
  JourneySummaryOut,
  RemoteSafeDashboardOut,
  RemoteSafeMeOut,
} from "@approvalready/shared-types";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";
import { RATING_LABELS, STATUS_LABELS, label, ratingClass } from "@/lib/remotesafe";

/** Shown to an organisation administrator while RemoteSafe is off. */
export function EnableRemoteSafe({ base, canEnable }: { base: string; canEnable: boolean }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function enable() {
    setBusy(true);
    const r = await apiRequest<RemoteSafeMeOut>("POST", `${base}/enable`, {});
    setBusy(false);
    if (!r.ok) setError(r.message);
    else router.refresh();
  }
  return (
    <section className="panel">
      <h1 className="page-title">RemoteSafe journey planning</h1>
      <p>
        Plan trips for people working in regional and remote areas: route legs, a transparent
        risk assessment, a pre-departure checklist and supervisor approval, with a PDF journey
        plan for the glovebox.
      </p>
      <FormError message={error} />
      {canEnable ? (
        <button type="button" className="button" disabled={busy} onClick={enable}>
          Turn on RemoteSafe for this organisation
        </button>
      ) : (
        <p className="muted">
          RemoteSafe is for business organisations. An organisation administrator can turn it on.
        </p>
      )}
    </section>
  );
}

export function JourneyList({
  journeys,
  empty,
  title,
}: {
  journeys: JourneySummaryOut[];
  empty: string;
  title: string;
}) {
  return (
    <section className="panel" aria-label={title}>
      <h2 className="section-title">{title}</h2>
      {journeys.length === 0 ? (
        <p className="muted">{empty}</p>
      ) : (
        <ul className="card-list">
          {journeys.map((j) => (
            <li key={j.id} className="card">
              <Link className="card-title" href={`/remotesafe/journeys/${j.id}`}>
                {j.title}
              </Link>
              <div className="muted">
                {j.reference} · {j.worker.display_name} · {j.origin} to {j.destination} · departs{" "}
                {j.departs.local}
              </div>
              <span className={`status status-${j.status.toLowerCase()}`}>
                {label(STATUS_LABELS, j.status)}
              </span>{" "}
              <span className={ratingClass(j.risk_outcome)}>
                {label(RATING_LABELS, j.risk_outcome)} risk
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function DashboardSummary({ d }: { d: RemoteSafeDashboardOut }) {
  const tiles: [string, number | string][] = [
    ["Waiting for my approval", d.awaiting_my_approval],
    ["Underway", d.active],
    ["Failed critical controls", d.critical_control_failures],
    [
      "Completed (of finished)",
      d.completion_rate === null || d.completion_rate === undefined
        ? "None yet"
        : `${Math.round(d.completion_rate * 100)}%`,
    ],
  ];
  return (
    <section className="panel" aria-label="Summary">
      <h2 className="section-title">
        {d.scope === "organisation" ? "Across the organisation" : "Your journeys"}
      </h2>
      <ul className="stat-tiles">
        {tiles.map(([k, v]) => (
          <li key={k}>
            <strong>{v}</strong> <span className="muted">{k}</span>
          </li>
        ))}
      </ul>
      {Object.keys(d.by_outcome).length ? (
        <p>
          By risk:{" "}
          {Object.entries(d.by_outcome)
            .map(([k, n]) => `${label(RATING_LABELS, k)} ${n}`)
            .join(" · ")}
        </p>
      ) : null}
      {d.repeated_hazards.length ? (
        <p>
          Hazards that keep coming up:{" "}
          {d.repeated_hazards.map((h) => `${String(h.title)} (${String(h.journeys)})`).join(", ")}
        </p>
      ) : null}
      {!d.monitoring_live ? (
        <p className="notice notice-warning">
          Check-in monitoring isn&apos;t live yet: overdue check-ins are not detected or
          escalated automatically. Journey monitors must follow up themselves.
        </p>
      ) : null}
    </section>
  );
}
