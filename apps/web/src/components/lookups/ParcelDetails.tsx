"use client";

import type { ParcelOut } from "@approvalready/shared-types";

import { apiRequest } from "@/lib/client-api";
import { formatDate } from "@/lib/questionnaire";

export type ParcelState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "found"; parcel: ParcelOut };

/** What the Queensland Government data says about a lot and plan. */
export async function fetchParcel(organisationId: string, lotPlan: string): Promise<ParcelState> {
  const result = await apiRequest<ParcelOut>(
    "GET",
    `/organisations/${organisationId}/lookups/parcels/${encodeURIComponent(lotPlan)}`,
  );
  if (result.ok) return { status: "found", parcel: result.data };
  return {
    status: "error",
    message:
      result.status === 404 ? "That lot and plan isn't in the state's land parcel data." : result.message,
  };
}

/** The state of a parcel lookup: checking, a problem, or the details. */
export function ParcelLookupResult({ state }: { state: ParcelState }) {
  if (state.status === "loading") return <p className="muted">Looking up the lot and plan…</p>;
  if (state.status === "error") return <p className="muted">{state.message}</p>;
  if (state.status === "found") return <ParcelDetails parcel={state.parcel} />;
  return null;
}

/** Lot, area, council and the state-mapped overlays, and what still has to be checked. */
export function ParcelDetails({ parcel }: { parcel: ParcelOut }) {
  const area = parcel.land_area_m2 ? `${Number(parcel.land_area_m2).toLocaleString("en-AU")} m²` : null;
  return (
    <div className="parcel-details" aria-label="Planning information">
      <p>
        <strong>{parcel.lot_plan_label}</strong>
        {area ? ` · ${area}` : ""}
        {parcel.tenure ? ` · ${parcel.tenure}` : ""}
        {parcel.local_authority ? ` · ${parcel.local_authority} council` : ""}
      </p>
      {parcel.overlays.length > 0 ? (
        <>
          <p>State mapping shows the land is in or touches:</p>
          <ul>
            {parcel.overlays.map((o) => (
              <li key={o.key}>
                {o.label} <span className="muted">({o.group})</span>
              </li>
            ))}
          </ul>
        </>
      ) : parcel.overlays_checked.length > 0 ? (
        <p>No state-mapped overlays found in: {parcel.overlays_checked.join(", ")}.</p>
      ) : null}
      {parcel.overlays_failed.length > 0 ? (
        <p className="muted">
          Couldn&apos;t check {parcel.overlays_failed.join(", ")} just now. Try again later.
        </p>
      ) : null}
      <details>
        <summary>Still to check yourself</summary>
        <ul>
          {parcel.not_checked.map((n) => (
            <li key={n.label}>
              <strong>{n.label}.</strong> {n.why}{" "}
              {n.where_to_check ? (
                <a href={n.where_to_check} target="_blank" rel="noreferrer">
                  Where to check
                </a>
              ) : null}
            </li>
          ))}
        </ul>
      </details>
      <p className="hint">
        Source: {parcel.source}, checked {formatDate(parcel.retrieved_at)}. Mapping is a guide,
        not a determination: confirm with the council before relying on it.
      </p>
    </div>
  );
}
