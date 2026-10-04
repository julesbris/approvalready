"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { apiRequest } from "@/lib/client-api";

export function SwitchButton({ organisationId, name }: { organisationId: string; name: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onClick() {
    setBusy(true);
    const result = await apiRequest("PUT", "/auth/session/organisation", {
      organisation_id: organisationId,
    });
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    router.refresh();
  }

  return (
    <>
      <button
        type="button"
        className="button-link"
        disabled={busy}
        onClick={onClick}
        aria-label={`Switch to ${name}`}
      >
        Switch to this organisation
      </button>
      {error ? (
        <span role="alert" className="field-error">
          {error}
        </span>
      ) : null}
    </>
  );
}
