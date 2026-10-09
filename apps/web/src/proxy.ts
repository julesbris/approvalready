import { type NextRequest, NextResponse } from "next/server";

import { nonceCsp } from "@/lib/csp";

/**
 * Per-request CSP nonce for dynamically rendered pages (see src/lib/csp.ts). Next.js reads the
 * nonce from the request's Content-Security-Policy header and applies it to its own scripts.
 */
export function proxy(request: NextRequest) {
  const nonce = btoa(crypto.randomUUID());
  const csp = nonceCsp(nonce, process.env.NODE_ENV === "development");
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("content-security-policy", csp);
  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("content-security-policy", csp);
  return response;
}

export const config = {
  matcher: [
    {
      // Keep in sync with NONCE_CSP_PATHS in src/lib/csp.ts (matchers must be literals).
      source:
        "/(login|register|verify-email|forgot-password|reset-password|account|invitations|projects|admin|review)(.*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
