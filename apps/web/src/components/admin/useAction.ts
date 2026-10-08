"use client";

import { useState } from "react";

import type { ApiResult } from "@/lib/client-api";

/** Busy and error state around API calls: `run` returns the data, or null after an error. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fields, setFields] = useState<Record<string, string>>({});

  async function run<T>(call: () => Promise<ApiResult<T>>): Promise<T | null> {
    setBusy(true);
    setError(null);
    setFields({});
    const result = await call();
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      setFields(result.fields ?? {});
      return null;
    }
    return result.data;
  }

  return { busy, error, fields, run, setError };
}
