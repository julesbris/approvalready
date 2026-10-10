/** Rules for the `/api/v1/*` backend-for-frontend proxy (kept pure so they are unit tested). */

/** Top-level API areas the browser may reach through the proxy. */
const PROXIED_ROOTS = new Set([
  "auth",
  "organisations",
  "invitations",
  "questionnaires",
  "admin",
  "professional",
  "ai",
  "partners",
  "privacy",
]);

/** Request headers forwarded to the API. Anything else (e.g. Authorization) is dropped. */
const FORWARDED_HEADERS = [
  "accept",
  "content-type",
  "cookie",
  "origin",
  "user-agent",
  "x-csrf-token",
  "x-request-id",
] as const;

export const RESPONSE_HEADERS = [
  "content-type",
  "retry-after",
  "x-request-id",
  // File downloads: always an attachment, sandboxed, or a redirect to a signed storage URL.
  "content-disposition",
  "content-security-policy",
  "location",
] as const;

export function isProxiedPath(path: readonly string[]): boolean {
  const [root] = path;
  return (
    root !== undefined &&
    PROXIED_ROOTS.has(root) &&
    path.every((segment) => segment !== "" && segment !== "." && segment !== "..")
  );
}

export function buildUpstreamHeaders(incoming: Headers): Headers {
  const headers = new Headers();
  for (const name of FORWARDED_HEADERS) {
    const value = incoming.get(name);
    if (value) headers.set(name, value);
  }
  // Caddy sets X-Forwarded-For from the real client address; pass it on so the API's
  // throttling and audit log see the user's IP rather than the web container's.
  const forwardedFor = incoming.get("x-forwarded-for");
  if (forwardedFor) headers.set("x-forwarded-for", forwardedFor);
  return headers;
}
