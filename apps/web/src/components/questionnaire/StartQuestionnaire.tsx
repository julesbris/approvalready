"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";

export function StartQuestionnaire({
  organisationId,
  projectId,
}: {
  organisationId: string;
  projectId: string;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start() {
    setBusy(true);
    setError(null);
    const result = await apiRequest(
      "POST",
      `/organisations/${organisationId}/projects/${projectId}/submissions`,
      {},
    );
    if (!result.ok) {
      setBusy(false);
      setError(result.message);
      return;
    }
    router.refresh();
  }

  return (
    <section className="panel">
      <h1 className="page-title">Tell us about your project</h1>
      <p className="muted">
        A short set of questions about your situation. Questions only appear when they apply to
        you, and you can save and come back at any time.
      </p>
      <FormError message={error} />
      <button type="button" className="button" disabled={busy} onClick={start}>
        {busy ? "Starting…" : "Start"}
      </button>
    </section>
  );
}
