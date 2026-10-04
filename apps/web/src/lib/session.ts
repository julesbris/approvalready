import "server-only";

import type { SessionOut } from "@approvalready/shared-types";
import { cookies, headers } from "next/headers";
import { notFound, redirect } from "next/navigation";

import { apiBaseUrl } from "@/lib/api";

export type ServerResult<T> = { ok: true; data: T } | { ok: false; status: number };

/**
 * GET an API path server-side with the browser's cookies (for rendering only: the API
 * re-checks every request, and all changes go through the browser and the CSRF check).
 */
export async function serverGet<T>(path: string): Promise<ServerResult<T>> {
  const cookieHeader = (await cookies()).toString();
  if (!cookieHeader) return { ok: false, status: 401 };
  const incoming = await headers();
  try {
    const response = await fetch(`${apiBaseUrl()}/v1${path}`, {
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
    if (!response.ok) return { ok: false, status: response.status };
    return { ok: true, data: (await response.json()) as T };
  } catch {
    return { ok: false, status: 0 };
  }
}

/** The signed-in user's session, or null when signed out. */
export async function getSession(): Promise<SessionOut | null> {
  const result = await serverGet<SessionOut>("/auth/session");
  return result.ok ? result.data : null;
}

/** The session, redirecting to sign-in (and back to `path`) when signed out. */
export async function requireSession(path: string): Promise<SessionOut> {
  const session = await getSession();
  if (!session) redirect(`/login?next=${encodeURIComponent(path)}`);
  return session;
}

/** Unwrap a server fetch for a page: 404s render the not-found page, other failures throw. */
export function orNotFound<T>(result: ServerResult<T>): T {
  if (result.ok) return result.data;
  if (result.status === 404 || result.status === 403) notFound();
  throw new Error(`API request failed (${result.status})`);
}
