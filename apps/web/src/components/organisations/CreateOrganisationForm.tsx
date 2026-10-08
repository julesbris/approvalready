"use client";

import type { OrganisationOut } from "@approvalready/shared-types";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";

export function CreateOrganisationForm() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const abn = String(form.get("abn") ?? "").trim();
    setBusy(true);
    setError(null);
    const created = await apiRequest<OrganisationOut>("POST", "/organisations", {
      name: String(form.get("name") ?? "").trim(),
      kind: "BUSINESS",
      abn: abn || null,
    });
    if (!created.ok) {
      setBusy(false);
      setError(created.message);
      return;
    }
    // Work in the new business straight away.
    await apiRequest("PUT", "/auth/session/organisation", { organisation_id: created.data.id });
    router.push(`/account/organisations/${created.data.id}`);
    router.refresh();
  }

  return (
    <form className="form" onSubmit={onSubmit}>
      <label>
        Business name
        <input name="name" required maxLength={200} autoComplete="organization" />
      </label>
      <label>
        ABN <span className="optional">(optional)</span>
        <input name="abn" inputMode="numeric" maxLength={14} />
      </label>
      <FormError message={error} />
      <div>
        <button type="submit" className="button" disabled={busy}>
          {busy ? "Adding…" : "Add business"}
        </button>
      </div>
    </form>
  );
}
