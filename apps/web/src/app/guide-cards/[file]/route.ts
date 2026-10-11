import { apiBaseUrl } from "@/lib/api";
import { cardRef } from "@/lib/marketing";

export const dynamic = "force-dynamic";

/**
 * A guide's image card (`/guide-cards/<ref>.jpg`), which Facebook and Instagram fetch when a
 * guide is posted. Served outside `/api/` because robots.txt keeps crawlers out of there.
 */
export async function GET(_request: Request, context: { params: Promise<{ file: string }> }) {
  const ref = cardRef((await context.params).file);
  if (!ref) return new Response("Not found", { status: 404 });
  let upstream: Response;
  try {
    upstream = await fetch(`${apiBaseUrl()}/v1/marketing/cards/${ref}.jpg`, {
      cache: "no-store",
      signal: AbortSignal.timeout(15_000),
    });
  } catch {
    return new Response("Unavailable", { status: 502 });
  }
  if (!upstream.ok) return new Response("Not found", { status: 404 });
  return new Response(await upstream.arrayBuffer(), {
    headers: { "content-type": "image/jpeg", "cache-control": "public, max-age=3600" },
  });
}
