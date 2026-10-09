"use client";

import type { ProjectDetailOut, PropertyOut } from "@approvalready/shared-types";
import { type FormEvent, useState } from "react";

import { FormError } from "@/components/auth/FormStatus";
import { AU_STATES } from "@/components/questionnaire/QuestionField";
import { apiRequest } from "@/lib/client-api";

type Props = {
  organisationId: string;
  project: ProjectDetailOut;
  properties: PropertyOut[];
  canWrite: boolean;
  onProjectChange: (project: ProjectDetailOut) => void;
};

export function propertyLabel(p: PropertyOut): string {
  const a = p.address;
  return [a.line1, a.line2, `${a.suburb} ${a.state} ${a.postcode}`].filter(Boolean).join(", ");
}

/** The property a project is about: pick one the organisation already has, or add one. */
export function SitePanel({ organisationId, project, canWrite, onProjectChange, ...props }: Props) {
  const [properties, setProperties] = useState(props.properties);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const org = `/organisations/${organisationId}`;
  const linked = properties.find((p) => p.id === project.property_id) ?? null;

  async function link(propertyId: string | null) {
    setBusy(true);
    setError(null);
    const result = await apiRequest<ProjectDetailOut>("PATCH", `${org}/projects/${project.id}`, {
      property_id: propertyId,
    });
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return false;
    }
    onProjectChange(result.data);
    return true;
  }

  async function addProperty(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const text = (name: string) => String(form.get(name) ?? "").trim();
    setBusy(true);
    setError(null);
    const created = await apiRequest<PropertyOut>("POST", `${org}/properties`, {
      address: {
        line1: text("line1"),
        line2: text("line2") || null,
        suburb: text("suburb"),
        state: text("state"),
        postcode: text("postcode"),
      },
      lot_plan: text("lot_plan") || null,
      land_area_m2: text("land_area_m2") || null,
    });
    setBusy(false);
    if (!created.ok) {
      setError(created.message);
      return;
    }
    setProperties((list) => [...list, created.data]);
    if (await link(created.data.id)) setAdding(false);
  }

  return (
    <section className="panel" aria-labelledby="site-title">
      <h2 id="site-title" className="section-title">
        Site
      </h2>
      <FormError message={error} />
      {linked ? (
        <>
          <p>{propertyLabel(linked)}</p>
          <p className="muted">
            {linked.lot_plan ? `Lot and plan ${linked.lot_plan}` : "Lot and plan not given"}
            {linked.land_area_m2 ? ` · ${linked.land_area_m2} m²` : ""}
          </p>
          <p className="hint">
            The questionnaire can fill in these details for you. We don&apos;t look up zoning or
            overlays yet, so those still come from you.
          </p>
        </>
      ) : (
        <p className="muted">
          Which property is this project about? Saving it here means you only type the address
          once.
        </p>
      )}
      {canWrite ? (
        <div className="button-row tight">
          {properties.length > 0 ? (
            <label>
              {linked ? "Change to" : "Choose a property"}
              <select
                value={linked?.id ?? ""}
                disabled={busy}
                onChange={(e) => link(e.target.value || null)}
              >
                <option value="">No property</option>
                {properties.map((p) => (
                  <option key={p.id} value={p.id}>
                    {propertyLabel(p)}
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
              Add a property
            </button>
          ) : null}
        </div>
      ) : null}
      {canWrite && adding ? (
        <form className="form" onSubmit={addProperty} aria-label="Add a property">
          <label>
            Street address
            <input name="line1" required maxLength={200} autoComplete="address-line1" />
          </label>
          <label>
            Address line 2 (optional)
            <input name="line2" maxLength={200} autoComplete="address-line2" />
          </label>
          <div className="field-row">
            <label>
              Suburb
              <input name="suburb" required maxLength={100} autoComplete="address-level2" />
            </label>
            <label>
              State
              <select name="state" required defaultValue="QLD">
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
                required
                inputMode="numeric"
                pattern="[0-9]{4}"
                maxLength={4}
                autoComplete="postal-code"
              />
            </label>
          </div>
          <div className="field-row">
            <label>
              Lot and plan (optional)
              <input name="lot_plan" maxLength={50} />
            </label>
            <label>
              Land area in m² (optional)
              <input name="land_area_m2" inputMode="decimal" />
            </label>
          </div>
          <div className="button-row tight">
            <button type="submit" className="button" disabled={busy}>
              Save property
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
