"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { apiRequest } from "@/lib/client-api";

/** Makes another of the user's organisations the active one and reloads the current page. */
export function SwitchOrganisationButton({
  organisationId,
  label,
}: {
  organisationId: string;
  label: string;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function change() {
    setBusy(true);
    setError(null);
    const result = await apiRequest("PUT", "/auth/session/organisation", {
      organisation_id: organisationId,
    });
    if (!result.ok) {
      setBusy(false);
      setError(result.message);
      return;
    }
    router.refresh();
  }

  return (
    <p>
      <button type="button" className="button" disabled={busy} onClick={change}>
        {label}
      </button>
      {error ? (
        <span role="alert" className="field-error">
          {" "}
          {error}
        </span>
      ) : null}
    </p>
  );
}
