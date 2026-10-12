"use client";

import type { AddressMatchOut, ListingImportOut } from "@approvalready/shared-types";
import { useId, useState } from "react";

import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";

type Props = {
  organisationId: string;
  /** The listing was read: its details (if any) and link, before an address is picked. */
  onImport: (listing: ListingImportOut) => void;
  onPick: (match: AddressMatchOut) => void;
  disabled?: boolean;
};

export function listingSummary(listing: ListingImportOut): string | null {
  const d = listing.details;
  const rooms = d
    ? [
        d.bedrooms != null ? `${d.bedrooms} bed` : null,
        d.bathrooms != null ? `${d.bathrooms} bath` : null,
        d.car_spaces != null ? `${d.car_spaces} car` : null,
      ].filter(Boolean)
    : [];
  const parts = [listing.property_type, rooms.join(", ") || null, d?.price_text ?? null];
  const text = parts.filter(Boolean).join(" · ");
  return text || null;
}

/** Paste a link from Domain, realestate.com.au, Homely or another property site. The
 * address comes from the link itself (the page is never copied); a Domain listing also
 * brings its bedrooms, bathrooms, car spaces and price when the server has a Domain key. */
export function ListingImport({ organisationId, onImport, onPick, disabled }: Props) {
  const id = useId();
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [listing, setListing] = useState<ListingImportOut | null>(null);

  async function bringIn(event: { preventDefault(): void }) {
    event.preventDefault();
    if (!url.trim()) return;
    setBusy(true);
    setError(null);
    const result = await apiRequest<ListingImportOut>(
      "POST",
      `/organisations/${organisationId}/lookups/listing`,
      { url: url.trim() },
    );
    setBusy(false);
    if (!result.ok) {
      setListing(null);
      setError(result.message);
      return;
    }
    setListing(result.data);
    onImport(result.data);
    const [only, ...others] = result.data.matches;
    if (only && others.length === 0) pick(only);
  }

  function pick(match: AddressMatchOut) {
    onPick(match);
    setListing((l) => (l ? { ...l, matches: [] } : l));
  }

  const summary = listing ? listingSummary(listing) : null;
  return (
    <div className="listing-import">
      <label htmlFor={`${id}-url`}>Have a listing? Paste its link</label>
      <div className="listing-import-row">
        <input
          id={`${id}-url`}
          type="url"
          inputMode="url"
          value={url}
          disabled={disabled || busy}
          placeholder="e.g. a link from Domain, realestate.com.au or Homely"
          aria-describedby={`${id}-hint`}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void bringIn(e);
          }}
        />
        <button
          type="button"
          className="button button-secondary"
          disabled={disabled || busy || !url.trim()}
          onClick={(e) => void bringIn(e)}
        >
          {busy ? "Reading…" : "Bring it in"}
        </button>
      </div>
      <p id={`${id}-hint`} className="hint">
        We read the address from the link and look up the rest from government data.
      </p>
      <FormError message={error} />
      {listing ? (
        <div className="listing-found" role="status">
          <p>
            <strong>From {listing.site_name}</strong>
            {summary ? `: ${summary}` : ""}
          </p>
          <p className="muted">
            {listing.note} {listing.how}
          </p>
          {listing.matches.length > 1 ? (
            <ul className="address-matches" aria-label="Addresses from the listing">
              {listing.matches.map((m) => (
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
      ) : null}
    </div>
  );
}
