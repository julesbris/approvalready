import { readFileSync } from "node:fs";
import path from "node:path";

import { type NextRequest, NextResponse } from "next/server";

import { nonceCsp, parseHashManifest, staticCsp, usesNonceCsp } from "@/lib/csp";

const isDev = process.env.NODE_ENV === "development";

let hashes: string[] | undefined;

/** Inline-script hashes of the statically generated pages, from the build (read once). */
function staticScriptHashes(): string[] {
  if (hashes === undefined) {
    try {
      hashes = parseHashManifest(
        readFileSync(path.join(process.cwd(), ".next", "csp-hashes.json"), "utf8"),
      );
    } catch {
      // Without the manifest no inline script may run: pages still render, without the
      // client-side extras. `npm run build` always writes it.
      if (!isDev) console.error("CSP: .next/csp-hashes.json is missing; run npm run build");
      hashes = [];
    }
  }
  return hashes;
}

/**
 * Content Security Policy for every page (see src/lib/csp.ts): a per-request nonce for
 * dynamically rendered pages, which Next.js reads from the request's Content-Security-Policy
 * header and applies to its own scripts, and the build's script hashes for static pages.
 */
export function proxy(request: NextRequest) {
  const pathname = request.nextUrl.pathname;
  if (pathname === "/") {
    // The partners host (partners.<domain>) opens on the partner portal.
    const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host") ?? "";
    if (host.startsWith("partners.")) {
      const url = request.nextUrl.clone();
      url.pathname = "/partner";
      return NextResponse.redirect(url);
    }
  }
  if (!usesNonceCsp(pathname)) {
    const response = NextResponse.next();
    response.headers.set("content-security-policy", staticCsp(isDev, staticScriptHashes()));
    return response;
  }
  const nonce = btoa(crypto.randomUUID());
  const csp = nonceCsp(nonce, isDev);
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
      // Every page, including not-found pages: not build assets or API routes (JSON).
      source: "/((?!_next/static|_next/image|api/|favicon\\.ico).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
