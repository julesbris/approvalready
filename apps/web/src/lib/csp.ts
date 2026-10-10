/**
 * Content Security Policy.
 *
 * Signed-in and auth pages are rendered per request, so they get a strict nonce-based policy
 * (set in `src/proxy.ts`): no 'unsafe-inline' for scripts. Public marketing and guide pages
 * are statically generated for SEO, where no per-request nonce can exist, so they keep the
 * baseline policy from next.config.ts. They carry no session-dependent content and make no
 * authenticated calls; moving them to hash-based CSP is tracked for Milestone 17.
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

export function staticCsp(isDev: boolean): string {
  return [
    ...COMMON,
    `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
  ].join("; ");
}
