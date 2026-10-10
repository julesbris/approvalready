/**
 * Content Security Policy.
 *
 * Signed-in and auth pages are rendered per request, so they get a strict nonce-based policy
 * (set in `src/proxy.ts`): no 'unsafe-inline' for scripts. Public marketing and guide pages
 * are statically generated for SEO, where no per-request nonce can exist, so they get a
 * hash-based policy instead (Milestone 17): `scripts/csp-hashes.mjs` hashes the inline
 * scripts Next.js wrote into the prerendered HTML at build time, and only those may run.
 * Both policies are set by `src/proxy.ts`, which runs for every page.
 */

/** Path prefixes rendered dynamically with the nonce policy. */
export const NONCE_CSP_PATHS = [
  "/login",
  "/register",
  "/verify-email",
  "/forgot-password",
  "/reset-password",
  "/account",
  "/invitations",
  "/projects",
  "/admin",
  "/review",
  "/notifications",
  "/partner",
  "/unsubscribe",
] as const;

export function usesNonceCsp(pathname: string): boolean {
  return NONCE_CSP_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

const COMMON = [
  "default-src 'self'",
  "img-src 'self' data: blob:",
  "font-src 'self'",
  "connect-src 'self'",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
];

export function nonceCsp(nonce: string, isDev: boolean): string {
  return [
    ...COMMON,
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${isDev ? " 'unsafe-eval'" : ""}`,
    // React/Next inject style attributes; nonces don't cover attributes, so styles stay
    // 'unsafe-inline' (style injection is far lower risk than script injection).
    "style-src 'self' 'unsafe-inline'",
  ].join("; ");
}

/**
 * Policy for statically generated pages. In production only the build's inline scripts (their
 * hashes) may run; development pages aren't prerendered, so they keep 'unsafe-inline'.
 */
export function staticCsp(isDev: boolean, scriptHashes: readonly string[]): string {
  const inline = isDev ? "'unsafe-inline' 'unsafe-eval'" : scriptHashes.join(" ");
  return [
    ...COMMON,
    `script-src 'self'${inline ? ` ${inline}` : ""}`,
    "style-src 'self' 'unsafe-inline'",
  ].join("; ");
}

const HASH = /^'sha256-[A-Za-z0-9+/]+={0,2}'$/;

/** The script hashes from the build's manifest (`.next/csp-hashes.json`); bad entries dropped. */
export function parseHashManifest(raw: string): string[] {
  const data: unknown = JSON.parse(raw);
  const list =
    data && typeof data === "object" && "scriptHashes" in data ? data.scriptHashes : undefined;
  if (!Array.isArray(list)) return [];
  return list.filter((h): h is string => typeof h === "string" && HASH.test(h));
}
