"use client";

import Link from "next/link";
import { useState } from "react";

import { FormError, FormNotice } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";

/**
 * One-click confirmation for an emailed token (email verification, invitation acceptance).
 * Deliberately needs a click: link scanners that prefetch email links must not consume it.
 */
export function TokenAction({
  path,
  token,
  label,
  success,
  next,
}: {
  path: string;
  token: string;
  label: string;
  success: string;
  next: { href: string; label: string };
}) {
  const [state, setState] = useState<"idle" | "busy" | "done">("idle");
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setState("busy");
    const result = await apiRequest("POST", path, { token });
    if (result.ok) {
      setState("done");
    } else {
      setState("idle");
      setError(result.message);
    }
  }

  if (state === "done") {
    return (
      <FormNotice>
        {success} <Link href={next.href}>{next.label}</Link>
      </FormNotice>
    );
  }
  return (
    <div className="form">
      <FormError message={error} />
      <button type="button" className="button" onClick={run} disabled={state === "busy"}>
        {label}
      </button>
    </div>
  );
}
