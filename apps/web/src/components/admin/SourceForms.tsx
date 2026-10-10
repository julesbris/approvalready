"use client";

import type { SourceDocumentOut, SourceOrganisationOut } from "@approvalready/shared-types";
import { useRouter } from "next/navigation";
import type { FormEvent } from "react";

import { useAction } from "@/components/admin/useAction";
import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";

export const ORGANISATION_KINDS: Record<string, string> = {
  LEGISLATURE: "Legislature",
  COUNCIL: "Council",
  STATE_AGENCY: "State agency",
  CTH_AGENCY: "Commonwealth agency",
  REGULATOR: "Regulator",
  GRANT_BODY: "Grant body",
};

export const SOURCE_TYPES: Record<string, string> = {
  LEGISLATION: "Legislation",
  REGULATION: "Regulation",
  PLANNING_SCHEME: "Planning scheme",
  POLICY: "Policy",
  GUIDELINE: "Guideline",
  FORM: "Form",
  FEE_SCHEDULE: "Fee schedule",
  WEBPAGE: "Web page",
  GRANT_GUIDELINES: "Grant guidelines",
};

const JURISDICTION_HINT = "CTH, a state (QLD, NSW…) or a council area such as LGA:QLD_CAIRNS";

function text(form: FormData, name: string): string | null {
  const value = String(form.get(name) ?? "").trim();
  return value === "" ? null : value;
}

/** Add a publisher of sources, and a source document with its provenance. */
export function SourceForms({ organisations }: { organisations: SourceOrganisationOut[] }) {
  const router = useRouter();
  const org = useAction();
  const doc = useAction();

  async function addOrganisation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const element = event.currentTarget;
    const form = new FormData(element);
    const created = await org.run(() =>
      apiRequest<SourceOrganisationOut>("POST", "/admin/source-organisations", {
        name: text(form, "name"),
        kind: text(form, "kind"),
        jurisdiction: text(form, "jurisdiction"),
        website: text(form, "website"),
      }),
    );
    if (created) {
      element.reset();
      router.refresh();
    }
  }

  async function addDocument(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const created = await doc.run(() =>
      apiRequest<SourceDocumentOut>("POST", "/admin/source-documents", {
        source_organisation_id: text(form, "organisation"),
        jurisdiction: text(form, "jurisdiction"),
        title: text(form, "title"),
        url: text(form, "url"),
        source_type: text(form, "source_type"),
        version_label: text(form, "version_label"),
        effective_from: text(form, "effective_from"),
        effective_to: text(form, "effective_to"),
        licence: text(form, "licence"),
      }),
    );
    if (created) router.push(`/admin/sources/${created.id}`);
  }

  return (
    <>
      <section className="panel" aria-labelledby="add-doc-title">
        <h2 id="add-doc-title" className="section-title">
          Add a source document
        </h2>
        {organisations.length === 0 ? (
          <p className="muted">Add the organisation that publishes it first.</p>
        ) : (
          <form
            method="post"
            className="form"
            onSubmit={addDocument}
            aria-label="Add a source document"
          >
            <FormError message={doc.error} />
            <label>
              Published by
              <select name="organisation" required defaultValue="">
                <option value="" disabled>
                  Choose…
                </option>
                {organisations.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Title
              <input name="title" required maxLength={300} />
            </label>
            <label>
              Address (URL) of the official source
              <input name="url" type="url" required maxLength={2000} placeholder="https://" />
            </label>
            <label>
              Type
              <select name="source_type" required defaultValue="">
                <option value="" disabled>
                  Choose…
                </option>
                {Object.entries(SOURCE_TYPES).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Jurisdiction
              <input name="jurisdiction" required placeholder="QLD" />
              <span className="hint">{JURISDICTION_HINT}</span>
            </label>
            <label>
              Version (optional)
              <input name="version_label" maxLength={100} placeholder="e.g. v2.4 or 1 July 2026" />
            </label>
            <div className="field-row">
              <label>
                In force from (optional)
                <input name="effective_from" type="date" />
              </label>
              <label>
                Until (optional, exclusive)
                <input name="effective_to" type="date" />
              </label>
            </div>
            <label>
              Licence or attribution (optional)
              <input name="licence" maxLength={200} placeholder="e.g. CC BY 4.0" />
            </label>
            <button type="submit" className="button" disabled={doc.busy}>
              Add document
            </button>
          </form>
        )}
      </section>

      <section className="panel" aria-labelledby="add-org-title">
        <h2 id="add-org-title" className="section-title">
          Add a source organisation
        </h2>
        <form
          method="post"
          className="form"
          onSubmit={addOrganisation}
          aria-label="Add a source organisation"
        >
          <FormError message={org.error} />
          <label>
            Name
            <input
              name="name"
              required
              maxLength={200}
              placeholder="e.g. Cairns Regional Council"
            />
          </label>
          <label>
            Kind
            <select name="kind" required defaultValue="">
              <option value="" disabled>
                Choose…
              </option>
              {Object.entries(ORGANISATION_KINDS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Jurisdiction
            <input name="jurisdiction" required placeholder="QLD" />
            <span className="hint">{JURISDICTION_HINT}</span>
          </label>
          <label>
            Website (optional)
            <input name="website" type="url" maxLength={500} placeholder="https://" />
          </label>
          <button type="submit" className="button button-secondary" disabled={org.busy}>
            Add organisation
          </button>
        </form>
      </section>
    </>
  );
}
