import { apiBaseUrl } from "@/lib/api";
import { cardFile } from "@/lib/marketing";

export const dynamic = "force-dynamic";

/**
 * A guide's image card (`/guide-cards/<ref>.jpg`, or `<ref>.wide.jpg` and `<ref>.portrait.jpg`
 * for the other sizes), which Facebook and Instagram fetch when a guide is posted and search
 * engines and link previews show for its page. Served outside `/api/` because robots.txt
 * keeps crawlers out of there.
 */
export async function GET(_request: Request, context: { params: Promise<{ file: string }> }) {
  const card = cardFile((await context.params).file);
  if (!card) return new Response("Not found", { status: 404 });
  const url = `${apiBaseUrl()}/v1/marketing/cards/${card.ref}.jpg?format=${card.format}`;
  let upstream: Response;
  try {
    upstream = await fetch(url, {
      cache: "no-store",
      signal: AbortSignal.timeout(15_000),
    });
  } catch {
    return new Response("Unavailable", { status: 502 });
  }
  if (!upstream.ok) return new Response("Not found", { status: 404 });
  return new Response(await upstream.arrayBuffer(), {
    headers: { "content-type": "image/jpeg", "cache-control": "public, max-age=86400" },
  });
}
