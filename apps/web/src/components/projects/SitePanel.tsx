"use client";

import type {
  AddressMatchOut,
  ProjectDetailOut,
  PropertyOut,
} from "@approvalready/shared-types";
import { type FormEvent, useState } from "react";

import { FormError } from "@/components/auth/FormStatus";
import { AddressSearch } from "@/components/lookups/AddressSearch";
import {
  fetchParcel,
  ParcelLookupResult,
  type ParcelState,
} from "@/components/lookups/ParcelDetails";
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

const EMPTY_FORM = {
  line1: "",
  line2: "",
  suburb: "",
  state: "QLD",
  postcode: "",
  lot_plan: "",
  land_area_m2: "",
};

/** The property a project is about: pick one the organisation already has, or add one.
 * Adding one starts from a Queensland address search that fills in the lot and plan and
 * land area, and shows what state mapping says about the land. */
export function SitePanel({ organisationId, project, canWrite, onProjectChange, ...props }: Props) {
  const [properties, setProperties] = useState(props.properties);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [picked, setPicked] = useState<ParcelState>({ status: "idle" });
  const [linkedParcel, setLinkedParcel] = useState<ParcelState>({ status: "idle" });
  const org = `/organisations/${organisationId}`;
  const linked = properties.find((p) => p.id === project.property_id) ?? null;
  const field = (name: keyof typeof EMPTY_FORM) => ({
    name,
    value: form[name],
    onChange: (e: { target: { value: string } }) =>
      setForm((f) => ({ ...f, [name]: e.target.value })),
  });


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
    const text = (name: keyof typeof EMPTY_FORM) => form[name].trim();
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
    if (await link(created.data.id)) closeForm();
  }

  function closeForm() {
    setAdding(false);
    setForm(EMPTY_FORM);
    setPicked({ status: "idle" });
  }

  async function pick(match: AddressMatchOut) {
    setForm((f) => ({
      ...f,
      line1: match.line1,
      line2: "",
      suburb: match.suburb,
      state: match.state,
      lot_plan: match.lot_plan_label ?? "",
      land_area_m2: "",
    }));
    if (!match.lot_plan) {
      setPicked({ status: "idle" });
      return;
    }
    setPicked({ status: "loading" });
    const state = await fetchParcel(organisationId, match.lot_plan);
    setPicked(state);
    // The parcel's area fills in the land area, unless one was typed meanwhile.
    const area = state.status === "found" ? state.parcel.land_area_m2 : null;
    if (area) setForm((f) => (f.land_area_m2 ? f : { ...f, land_area_m2: String(Number(area)) }));
  }

  async function checkLinked(lotPlan: string) {
    setLinkedParcel({ status: "loading" });
    setLinkedParcel(await fetchParcel(organisationId, lotPlan));
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
            The questionnaire can fill in these details for you, with the council area, land
            area and state-mapped overlays for Queensland land. The zone still comes from you.
          </p>
          {linked.lot_plan && linked.address.state === "QLD" && linkedParcel.status === "idle" ? (
            <button
              type="button"
              className="button button-secondary"
              onClick={() => checkLinked(linked.lot_plan as string)}
            >
              Show planning information
            </button>
          ) : null}
          <ParcelLookupResult state={linkedParcel} />
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
          <AddressSearch organisationId={organisationId} onPick={pick} disabled={busy} />
          <ParcelLookupResult state={picked} />
          <label>
            Street address
            <input {...field("line1")} required maxLength={200} autoComplete="address-line1" />
          </label>
          <label>
            Address line 2 (optional)
            <input {...field("line2")} maxLength={200} autoComplete="address-line2" />
          </label>
          <div className="field-row">
            <label>
              Suburb
              <input {...field("suburb")} required maxLength={100} autoComplete="address-level2" />
            </label>
            <label>
              State
              <select {...field("state")} required>
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
                {...field("postcode")}
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
              <input {...field("lot_plan")} maxLength={50} />
            </label>
            <label>
              Land area in m² (optional)
              <input {...field("land_area_m2")} inputMode="decimal" />
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
              onClick={closeForm}
            >
              Cancel
            </button>
          </div>
        </form>
      ) : null}
    </section>
  );
}
