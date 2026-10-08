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
    setBusy(true);
    setError(null);
    const result = await apiRequest<ProjectOut>("POST", `/organisations/${organisationId}/projects`, {
      vertical,
      title: String(form.get("title") ?? "").trim(),
      description: description || null,
    });
    if (!result.ok) {
      setBusy(false);
      setError(result.message);
      return;
    }
    router.push(`/projects/${result.data.id}`);
  }

  return (
    <form className="form form-wide" onSubmit={onSubmit}>
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
        Project name
        <input name="title" required maxLength={200} placeholder="For example: Granny flat at Edge Hill" />
      </label>
      <label>
        Notes (optional)
        <textarea name="description" maxLength={2000} rows={3} />
      </label>
      <FormError message={error} />
      <div>
        <button type="submit" className="button" disabled={busy}>
          {busy ? "Creating…" : "Create project"}
        </button>
      </div>
    </form>
  );
}
