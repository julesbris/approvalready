import "server-only";

import type { SessionOut } from "@approvalready/shared-types";
import { cookies, headers } from "next/headers";

import { apiBaseUrl } from "@/lib/api";

/**
 * The signed-in user's session, fetched server-side from the API with the browser's cookies.
 * Returns null when signed out. For rendering only: the API re-checks every request.
 */
export async function getSession(): Promise<SessionOut | null> {
  const cookieHeader = (await cookies()).toString();
  if (!cookieHeader) return null;
  const incoming = await headers();
  try {
    const response = await fetch(`${apiBaseUrl()}/v1/auth/session`, {
      headers: {
        cookie: cookieHeader,
        accept: "application/json",
        "user-agent": incoming.get("user-agent") ?? "",
        ...(incoming.get("x-forwarded-for")
          ? { "x-forwarded-for": incoming.get("x-forwarded-for") as string }
          : {}),
      },
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) return null;
    return (await response.json()) as SessionOut;
  } catch {
    return null;
  }
}
