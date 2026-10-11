"use client";

import type { ProjectOut, Vertical } from "@approvalready/shared-types";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { FormError } from "@/components/auth/FormStatus";
import { defaultBrand } from "@/lib/brand";
import { apiRequest } from "@/lib/client-api";

export function NewProjectForm({
  organisationId,
  initialVertical,
}: {
  organisationId: string;
  initialVertical: Vertical | null;
}) {
  const router = useRouter();
  const [vertical, setVertical] = useState<Vertical | null>(initialVertical);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!vertical) {
      setError("Choose what the project is about.");
      return;
    }
    const form = new FormData(event.currentTarget);
    const description = String(form.get("description") ?? "").trim();
    const product = defaultBrand.products.find((p) => p.key === vertical);
    setBusy(true);
    setError(null);
    const base = `/organisations/${organisationId}`;
    const result = await apiRequest<ProjectOut>("POST", `${base}/projects`, {
      vertical,
      // A name is optional: one can be given later.
      title: String(form.get("title") ?? "").trim() || `${product?.name ?? "New"} project`,
      description: description || null,
    });
    if (!result.ok) {
      setBusy(false);
      setError(result.message);
      return;
    }
    // Straight into the questions; the project page is there if they can't start yet.
    const project = result.data.id;
    const started = await apiRequest("POST", `${base}/projects/${project}/submissions`, {});
    router.push(started.ok ? `/projects/${project}/questionnaire` : `/projects/${project}`);
  }

  return (
    <form method="post" className="form form-wide" onSubmit={onSubmit}>
      <fieldset className="choice-grid">
        <legend>What is the project about?</legend>
        {defaultBrand.products.map((product) => (
          <label key={product.key} className="choice">
            <input
              type="radio"
              name="vertical"
              value={product.key}
              checked={vertical === product.key}
              onChange={() => setVertical(product.key)}
            />
            <span>
              <strong>{product.name}</strong>
              <span className="muted">{product.question}</span>
            </span>
          </label>
        ))}
      </fieldset>
      <label>
        Project name <span className="optional">(optional)</span>
        <input name="title" maxLength={200} placeholder="For example: Granny flat at Edge Hill" />
      </label>
      <details className="form-more">
        <summary>Add notes</summary>
        <label>
          Notes <span className="optional">(optional)</span>
          <textarea name="description" maxLength={2000} rows={3} />
        </label>
      </details>
      <FormError message={error} />
      <div>
        <button type="submit" className="button" disabled={busy}>
          {busy ? "Starting…" : "Continue"}
        </button>
      </div>
    </form>
  );
}
