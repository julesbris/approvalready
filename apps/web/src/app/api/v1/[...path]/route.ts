import type { NextRequest } from "next/server";

import { apiBaseUrl } from "@/lib/api";
import { buildUpstreamHeaders, isProxiedPath, RESPONSE_HEADERS } from "@/lib/bff";

export const dynamic = "force-dynamic";

/**
 * Backend-for-frontend proxy: the browser talks only to this origin, so session cookies stay
 * host-only (`__Host-`) on the web host and the API is never called cross-origin with
 * credentials. Cookies, the CSRF header and Set-Cookie pass through unchanged; the API makes
 * every authorisation decision.
 */
async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  if (!isProxiedPath(path)) {
    return Response.json({ detail: { code: "not_found", message: "Not found." } }, { status: 404 });
  }
  const url = new URL(`${apiBaseUrl()}/v1/${path.map(encodeURIComponent).join("/")}`);
  url.search = request.nextUrl.search;

  const hasBody = !["GET", "HEAD"].includes(request.method);
  let upstream: Response;
  try {
    upstream = await fetch(url, {
      method: request.method,
      headers: buildUpstreamHeaders(request.headers),
      body: hasBody ? await request.arrayBuffer() : undefined,
      cache: "no-store",
      redirect: "manual",
      signal: AbortSignal.timeout(15_000),
    });
  } catch {
    return Response.json(
      { detail: { code: "upstream_unavailable", message: "Service unavailable. Try again." } },
      { status: 502 },
    );
  }

  const headers = new Headers();
  for (const name of RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }
  for (const cookie of upstream.headers.getSetCookie()) headers.append("set-cookie", cookie);
  headers.set("cache-control", "no-store");
  const body = upstream.status === 204 ? null : await upstream.arrayBuffer();
  return new Response(body, { status: upstream.status, headers });
}

export { proxy as DELETE, proxy as GET, proxy as PATCH, proxy as POST, proxy as PUT };
