"use client";

import type { VesselLookupOut } from "@approvalready/shared-types";
import { useId, useState } from "react";

import { apiRequest } from "@/lib/client-api";
import { formatDate } from "@/lib/questionnaire";

type Props = {
  organisationId: string;
  disabled?: boolean;
  /** Called with AMSA's record so a form can fill itself in. */
  onFound?: (record: VesselLookupOut) => void;
  /** Look up this UVI (a saved vessel's) instead of asking for one. */
  uvi?: string;
  /** Show the record here once found. */
  showRecord?: boolean;
};

/** Find a domestic commercial vessel in AMSA's published list by its UVI. */
export function VesselLookup({ organisationId, disabled, onFound, uvi, showRecord }: Props) {
  const id = useId();
  const [typed, setTyped] = useState("");
  const [record, setRecord] = useState<VesselLookupOut | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function lookUp() {
    const value = (uvi ?? typed).trim();
    if (!value) return;
    setBusy(true);
    setMessage(null);
    const result = await apiRequest<VesselLookupOut>(
      "GET",
      `/organisations/${organisationId}/lookups/vessels/${encodeURIComponent(value)}`,
    );
    setBusy(false);
    if (!result.ok) {
      setRecord(null);
      setMessage(result.message);
      return;
    }
    setRecord(result.data);
    onFound?.(result.data);
  }

  return (
    <div className="vessel-lookup">
      {uvi ? (
        <button
          type="button"
          className="button button-secondary"
          disabled={disabled || busy}
          onClick={lookUp}
        >
          {busy ? "Checking…" : "Check AMSA's record"}
        </button>
      ) : (
        <>
          <label htmlFor={`${id}-uvi`}>Start with the vessel&apos;s UVI</label>
          <div className="button-row tight">
            <input
              id={`${id}-uvi`}
              value={typed}
              maxLength={20}
              disabled={disabled || busy}
              aria-describedby={`${id}-hint`}
              onChange={(e) => setTyped(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void lookUp();
                }
              }}
            />
            <button
              type="button"
              className="button button-secondary"
              disabled={disabled || busy || !typed.trim()}
              onClick={lookUp}
            >
              {busy ? "Looking up…" : "Look up"}
            </button>
          </div>
          <p id={`${id}-hint`} className="hint">
            The unique vessel identifier AMSA issued, shown on the certificate of survey. We
            fill in what AMSA&apos;s list of commercial vessels says. No UVI? Fill in the fields
            below.
          </p>
        </>
      )}
      {message ? <p className="muted">{message}</p> : null}
      {showRecord && record ? <VesselRecord record={record} /> : null}
    </div>
  );
}

/** What AMSA's list says about a vessel. */
export function VesselRecord({ record }: { record: VesselLookupOut }) {
  return (
    <div className="vessel-record" aria-label="AMSA record">
      <p>
        <strong>{record.name ?? "Unnamed vessel"}</strong> · UVI {record.uvi}
      </p>
      <dl className="record-fields">
        {Object.entries(record.fields).map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <p className="hint">
        Source: {record.source}, list downloaded {formatDate(record.list_retrieved_at)}.{" "}
        {record.note}
      </p>
    </div>
  );
}
