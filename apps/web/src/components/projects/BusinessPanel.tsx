"use client";

import type { BusinessProfileOut, ProjectDetailOut } from "@approvalready/shared-types";
import { type FormEvent, useState } from "react";

import { FormError } from "@/components/auth/FormStatus";
import { AU_STATES } from "@/components/questionnaire/QuestionField";
import { apiRequest } from "@/lib/client-api";

type Props = {
  organisationId: string;
  project: ProjectDetailOut;
  businesses: BusinessProfileOut[];
  canWrite: boolean;
  onProjectChange: (project: ProjectDetailOut) => void;
};

const ENTITY_TYPES: [string, string][] = [
  ["SOLE_TRADER", "Sole trader"],
  ["PARTNERSHIP", "Partnership"],
  ["COMPANY", "Company"],
  ["TRUST", "Trust"],
  ["INCORPORATED_ASSOCIATION", "Incorporated association"],
  ["COOPERATIVE", "Co-operative"],
  ["OTHER", "Other"],
];

const EMPLOYEE_BANDS: [string, string][] = [
  ["NONE", "Just me"],
  ["1_4", "1 to 4 employees"],
  ["5_19", "5 to 19 employees"],
  ["20_199", "20 to 199 employees"],
  ["200_PLUS", "200 or more employees"],
];

const TURNOVER_BANDS: [string, string][] = [
  ["UNDER_75K", "Under $75,000"],
  ["75K_2M", "$75,000 to $2 million"],
  ["2M_10M", "$2 million to $10 million"],
  ["10M_50M", "$10 million to $50 million"],
  ["OVER_50M", "Over $50 million"],
];

export function businessLabel(b: BusinessProfileOut): string {
  const name = b.trading_name ? `${b.trading_name} (${b.legal_name})` : b.legal_name;
  return b.abn ? `${name} · ABN ${formatAbn(b.abn)}` : name;
}

export function formatAbn(abn: string): string {
  return abn.replace(/^(\d{2})(\d{3})(\d{3})(\d{3})$/, "$1 $2 $3 $4");
}

/** The business a project is about: pick one the organisation already has, or add one. */
export function BusinessPanel({
  organisationId,
  project,
  canWrite,
  onProjectChange,
  ...props
}: Props) {
  const [businesses, setBusinesses] = useState(props.businesses);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const org = `/organisations/${organisationId}`;
  const linked = businesses.find((b) => b.id === project.business_profile_id) ?? null;

  async function link(businessId: string | null) {
    setBusy(true);
    setError(null);
    const result = await apiRequest<ProjectDetailOut>("PATCH", `${org}/projects/${project.id}`, {
      business_profile_id: businessId,
    });
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return false;
    }
    onProjectChange(result.data);
    return true;
  }

  async function addBusiness(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const text = (name: string) => String(form.get(name) ?? "").trim();
    const line1 = text("line1");
    setBusy(true);
    setError(null);
    const created = await apiRequest<BusinessProfileOut>("POST", `${org}/business-profiles`, {
      legal_name: text("legal_name"),
      trading_name: text("trading_name") || null,
      entity_type: text("entity_type"),
      abn: text("abn") || null,
      employee_band: text("employee_band") || null,
      turnover_band: text("turnover_band") || null,
      address: line1
        ? {
            line1,
            line2: null,
            suburb: text("suburb"),
            state: text("state"),
            postcode: text("postcode"),
          }
        : null,
    });
    setBusy(false);
    if (!created.ok) {
      setError(created.message);
      return;
    }
    setBusinesses((list) => [...list, created.data]);
    if (await link(created.data.id)) setAdding(false);
  }

  return (
    <section className="panel" aria-labelledby="business-title">
      <h2 id="business-title" className="section-title">
        Business
      </h2>
      <FormError message={error} />
      {linked ? (
        <>
          <p>{businessLabel(linked)}</p>
          <p className="hint">
            The questionnaire can fill in your ABN, structure, size and address from these
            details.
          </p>
        </>
      ) : (
        <p className="muted">
          Which business is this project about? Saving it here means you only type its details
          once.
        </p>
      )}
      {canWrite ? (
        <div className="button-row tight">
          {businesses.length > 0 ? (
            <label>
              {linked ? "Change to" : "Choose a business"}
              <select
                value={linked?.id ?? ""}
                disabled={busy}
                onChange={(e) => link(e.target.value || null)}
              >
                <option value="">No business</option>
                {businesses.map((b) => (
                  <option key={b.id} value={b.id}>
                    {businessLabel(b)}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {!adding ? (
            <button
              type="button"
              className="button button-secondary"
              disabled={busy}
              onClick={() => setAdding(true)}
            >
              Add a business
            </button>
          ) : null}
        </div>
      ) : null}
      {canWrite && adding ? (
        <form method="post" className="form" onSubmit={addBusiness} aria-label="Add a business">
          <label>
            Legal name
            <input name="legal_name" required maxLength={200} autoComplete="organization" />
          </label>
          <label>
            Trading name (optional)
            <input name="trading_name" maxLength={200} />
          </label>
          <div className="field-row">
            <label>
              Structure
              <select name="entity_type" required defaultValue="SOLE_TRADER">
                {ENTITY_TYPES.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              ABN (optional)
              <input name="abn" inputMode="numeric" maxLength={14} />
            </label>
          </div>
          <div className="field-row">
            <label>
              People working in it (optional)
              <select name="employee_band" defaultValue="">
                <option value="">Not sure yet</option>
                {EMPLOYEE_BANDS.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Expected yearly turnover (optional)
              <select name="turnover_band" defaultValue="">
                <option value="">Not sure yet</option>
                {TURNOVER_BANDS.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label>
            Business address (optional)
            <input name="line1" maxLength={200} autoComplete="address-line1" />
          </label>
          <div className="field-row">
            <label>
              Suburb
              <input name="suburb" maxLength={100} autoComplete="address-level2" />
            </label>
            <label>
              State
              <select name="state" defaultValue="QLD">
                {AU_STATES.map(([code, name]) => (
                  <option key={code} value={code}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Postcode
              <input
                name="postcode"
                inputMode="numeric"
                pattern="[0-9]{4}"
                maxLength={4}
                autoComplete="postal-code"
              />
            </label>
          </div>
          <div className="button-row tight">
            <button type="submit" className="button" disabled={busy}>
              Save business
            </button>
            <button
              type="button"
              className="button button-secondary"
              disabled={busy}
              onClick={() => setAdding(false)}
            >
              Cancel
            </button>
          </div>
        </form>
      ) : null}
    </section>
  );
}
