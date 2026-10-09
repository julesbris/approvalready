"use client";

import type { AddressMatchOut, AddressSearchOut } from "@approvalready/shared-types";
import { useEffect, useId, useRef, useState } from "react";

import { apiRequest } from "@/lib/client-api";

type Props = {
  organisationId: string;
  onPick: (match: AddressMatchOut) => void;
  disabled?: boolean;
  /** Wait this long after typing stops before searching. */
  delayMs?: number;
};

/** Search Queensland addresses as you type and pick one. Picking fills in the address and
 * its lot and plan; nothing is saved until the form it sits in is. */
export function AddressSearch({ organisationId, onPick, disabled, delayMs = 350 }: Props) {
  const id = useId();
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState<AddressMatchOut[] | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);

  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latest = useRef(0);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  function search(text: string) {
    setQuery(text);
    if (timer.current) clearTimeout(timer.current);
    const request = ++latest.current;
    const q = text.trim();
    if (q.length < 4) {
      setMatches(null);
      setMessage(null);
      setSearching(false);
      return;
    }
    timer.current = setTimeout(async () => {
      setSearching(true);
      const result = await apiRequest<AddressSearchOut>(
        "GET",
        `/organisations/${organisationId}/lookups/addresses?q=${encodeURIComponent(q)}`,
      );
      if (request !== latest.current) return; // a newer search has started
      setSearching(false);
      if (!result.ok) {
        setMatches(null);
        setMessage(result.message);
        return;
      }
      setMatches(result.data.matches);
      setMessage(
        result.data.matches.length === 0
          ? "No Queensland address matches yet. Keep typing, or fill in the fields below."
          : null,
      );
    }, delayMs);
  }

  function pick(match: AddressMatchOut) {
    onPick(match);
    latest.current += 1;
    setQuery("");
    setMatches(null);
    setMessage(null);
  }

  return (
    <div className="address-search">
      <label htmlFor={`${id}-q`}>Find a Queensland address</label>
      <input
        id={`${id}-q`}
        type="search"
        value={query}
        disabled={disabled}
        placeholder="Start typing, e.g. 34 Gilmore St Bentley Park"
        autoComplete="off"
        aria-describedby={`${id}-hint`}
        onChange={(e) => search(e.target.value)}
      />
      <p id={`${id}-hint`} className="hint">
        From the Queensland Government&apos;s address and land parcel data. Outside Queensland,
        fill in the fields below.
      </p>
      {searching ? <p className="muted">Searching…</p> : null}
      {message ? <p className="muted">{message}</p> : null}
      {matches && matches.length > 0 ? (
        <ul className="address-matches" aria-label="Matching addresses">
          {matches.map((m) => (
            <li key={m.address_pid}>
              <button type="button" className="button-link" onClick={() => pick(m)}>
                {m.label}
              </button>
              {m.lot_plan_label ? <span className="muted"> · {m.lot_plan_label}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
