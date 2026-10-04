import type { ReadyResponse } from "@approvalready/shared-types";

/** Server-side base URL for the API (internal Docker network in deployed environments). */
export function apiBaseUrl(): string {
  return process.env.API_INTERNAL_URL ?? "http://localhost:8000";
}

export type ApiProbe = { status: "ok" | "degraded" | "unreachable"; detail?: ReadyResponse };

export async function probeApi(fetchImpl: typeof fetch = fetch, timeoutMs = 2000): Promise<ApiProbe> {
  try {
    const response = await fetchImpl(`${apiBaseUrl()}/health/ready`, {
      cache: "no-store",
      signal: AbortSignal.timeout(timeoutMs),
    });
    const detail = (await response.json()) as ReadyResponse;
    return { status: response.ok && detail.status === "ok" ? "ok" : "degraded", detail };
  } catch {
    return { status: "unreachable" };
  }
}
