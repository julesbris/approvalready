"use client";

import type { MarketplaceCategoryOut, PartnerOut } from "@approvalready/shared-types";
import { type FormEvent, useState } from "react";

import { useAction } from "@/components/admin/useAction";
import { FormError, FormNotice } from "@/components/auth/FormStatus";
import { AreaPicker, CredentialPicker } from "@/components/partners/ApplyForm";
import { apiRequest } from "@/lib/client-api";
import {
  CATEGORY_STATUS_LABELS,
  CREDENTIAL_KIND_LABELS,
  CREDENTIAL_STATUS_LABELS,
  areaLabel,
  formatCover,
} from "@/lib/partners";
import { formatDate } from "@/lib/questionnaire";

type Props = {
  organisationId: string;
  initial: PartnerOut;
  categories: MarketplaceCategoryOut[];
  canManage: boolean;
};

/** The partner's own profile: details, categories, service areas and credentials. */
export function PartnerProfile({ organisationId, initial, categories, canManage }: Props) {
  const [partner, setPartner] = useState(initial);
  const [name, setName] = useState(initial.name);
  const [abn, setAbn] = useState(initial.abn ?? "");
  const [website, setWebsite] = useState(initial.website ?? "");
  const [phone, setPhone] = useState(initial.phone ?? "");
  const [email, setEmail] = useState(initial.contact_email ?? "");
  const [description, setDescription] = useState(initial.description ?? "");
  const [newCategory, setNewCategory] = useState("");
  const [saved, setSaved] = useState(false);
  const { busy, error, run } = useAction();
  const base = `/organisations/${organisationId}/partner`;

  async function call(method: "POST" | "PATCH" | "DELETE", path: string, body?: unknown) {
    setSaved(false);
    const updated = await run(() => apiRequest<PartnerOut>(method, `${base}${path}`, body));
    if (updated) setPartner(updated);
    return updated;
  }

  async function saveDetails(event: FormEvent) {
    event.preventDefault();
    const body: Record<string, unknown> = {
      website,
      phone,
      contact_email: email,
      description,
    };
    if (!partner.details_locked) {
      body.name = name;
      body.abn = abn;
    }
    if (await call("PATCH", "", body)) setSaved(true);
  }

  const chosenKeys = new Set(partner.categories.map((c) => c.category_key));
  const available = categories.filter((c) => !chosenKeys.has(c.key));
  const needsCredential = partner.categories
    .filter((c) => c.requires_credential)
    .map((c): [string, string] => [c.category_key, c.label]);
  const licences = partner.credentials.filter(
    (c) => c.kind === "LICENCE" || c.kind === "ACCREDITATION",
  );

  return (
    <div>
      <FormError message={error} />
      <section className="panel" aria-labelledby="details-title">
        <h2 id="details-title" className="section-title">
          Business details
        </h2>
        <form method="post" className="form" onSubmit={saveDetails}>
          <label>
            Business name
            <input
              value={name}
              maxLength={200}
              disabled={!canManage || partner.details_locked}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label>
            ABN
            <input
              value={abn}
              maxLength={14}
              disabled={!canManage || partner.details_locked}
              onChange={(e) => setAbn(e.target.value)}
            />
          </label>
          {partner.details_locked ? (
            <p className="muted">We checked your business name and ABN. Contact us to change them.</p>
          ) : null}
          <label>
            Website
            <input
              value={website}
              maxLength={300}
              disabled={!canManage}
              onChange={(e) => setWebsite(e.target.value)}
            />
          </label>
          <label>
            Phone for customers
            <input
              value={phone}
              maxLength={30}
              disabled={!canManage}
              onChange={(e) => setPhone(e.target.value)}
            />
          </label>
          <label>
            Email for customers
            <input
              type="email"
              value={email}
              maxLength={320}
              disabled={!canManage}
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>
          <label>
            What your business does
            <textarea
              value={description}
              rows={4}
              maxLength={2000}
              disabled={!canManage}
              onChange={(e) => setDescription(e.target.value)}
            />
          </label>
          {canManage ? (
            <div className="button-row">
              <button type="submit" className="button" disabled={busy}>
                Save details
              </button>
            </div>
          ) : null}
          {saved ? <FormNotice>Saved.</FormNotice> : null}
        </form>
      </section>

      <section className="panel" aria-labelledby="categories-title">
        <h2 id="categories-title" className="section-title">
          Categories
        </h2>
        <ul className="task-list" aria-label="Your categories">
          {partner.categories.map((c) => (
            <li key={c.id} className="task">
              <span>
                <strong>{c.label}</strong>{" "}
                <span className="badge">{CATEGORY_STATUS_LABELS[c.status]}</span>
                {c.counts ? <span className="badge">Receiving referrals</span> : null}
                {c.notes ? (
                  <span className="muted">
                    <br />
                    Our note: {c.notes}
                  </span>
                ) : null}
                {!c.counts && c.problems.length > 0 ? (
                  <span className="muted">
                    <br />
                    {c.problems.join(" ")}
                  </span>
                ) : null}
              </span>
              {c.requires_credential && canManage ? (
                <label>
                  <span className="visually-hidden">Licence for {c.label}</span>
                  <select
                    value={c.credential_id ?? ""}
                    disabled={busy}
                    onChange={(e) =>
                      void call("PATCH", `/categories/${c.id}`, {
                        credential_id: e.target.value || null,
                      })
                    }
                  >
                    <option value="">Choose the licence that covers it</option>
                    {licences.map((l) => (
                      <option key={l.id} value={l.id}>
                        {l.issuer} {l.number}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
              {canManage ? (
                <button
                  type="button"
                  className="button-link"
                  disabled={busy}
                  onClick={() => void call("DELETE", `/categories/${c.id}`)}
                >
                  Remove
                </button>
              ) : null}
            </li>
          ))}
        </ul>
        {canManage && available.length > 0 ? (
          <div className="form inline-form">
            <label>
              Add a category
              <select value={newCategory} onChange={(e) => setNewCategory(e.target.value)}>
                <option value="">Choose…</option>
                {available.map((c) => (
                  <option key={c.key} value={c.key}>
                    {c.label}
                    {c.requires_credential ? " (licence needed)" : ""}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="button-secondary"
              disabled={busy || !newCategory}
              onClick={async () => {
                if (await call("POST", "/categories", { category_key: newCategory })) {
                  setNewCategory("");
                }
              }}
            >
              Add
            </button>
          </div>
        ) : null}
      </section>

      <section className="panel" aria-labelledby="areas-title">
        <h2 id="areas-title" className="section-title">
          Service areas
        </h2>
        <ul className="task-list" aria-label="Your service areas">
          {partner.service_areas.map((a) => (
            <li key={a.id} className="task">
              <span>
                {areaLabel(a)}
                {!a.counts ? (
                  <span className="muted"> (more than your plan covers)</span>
                ) : null}
              </span>
              {canManage ? (
                <button
                  type="button"
                  className="button-link"
                  disabled={busy}
                  onClick={() => void call("DELETE", `/service-areas/${a.id}`)}
                >
                  Remove
                </button>
              ) : null}
            </li>
          ))}
        </ul>
        {canManage ? (
          <AreaPicker busy={busy} onAdd={async (a) => void (await call("POST", "/service-areas", a))} />
        ) : null}
      </section>

      <section className="panel" aria-labelledby="credentials-title">
        <h2 id="credentials-title" className="section-title">
          Licences and insurance
        </h2>
        <p className="muted">
          We check each one against the issuer&apos;s public register. Adding a licence to an
          approved category sends that category back for checking.
        </p>
        <ul className="task-list" aria-label="Your credentials">
          {partner.credentials.map((c) => (
            <li key={c.id} className="task">
              <span>
                {CREDENTIAL_KIND_LABELS[c.kind]}: {c.issuer} {c.number}
                {c.cover_cents ? `, cover ${formatCover(c.cover_cents)}` : ""}
                {c.expires_on ? `, expires ${formatDate(c.expires_on)}` : ""}
                {c.notes ? (
                  <span className="muted">
                    <br />
                    Our note: {c.notes}
                  </span>
                ) : null}
              </span>
              <span className="badge">
                {CREDENTIAL_STATUS_LABELS[c.status]}
                {c.status === "VERIFIED" && !c.current ? " (expired)" : ""}
              </span>
              {canManage ? (
                <button
                  type="button"
                  className="button-link"
                  disabled={busy}
                  onClick={() => void call("DELETE", `/credentials/${c.id}`)}
                >
                  Remove
                </button>
              ) : null}
            </li>
          ))}
        </ul>
        {canManage ? (
          <CredentialPicker
            busy={busy}
            categories={needsCredential}
            onAdd={async (c) => void (await call("POST", "/credentials", c))}
          />
        ) : null}
      </section>
    </div>
  );
}
