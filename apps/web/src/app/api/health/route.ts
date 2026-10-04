import { NextResponse } from "next/server";

import { probeApi } from "@/lib/api";

export const dynamic = "force-dynamic";

/**
 * Web liveness. Always 200 while the Next.js process serves, so an API outage does not get
 * healthy web containers restarted; the API's state is reported for operators.
 */
export async function GET() {
  const api = await probeApi();
  return NextResponse.json(
    { status: "ok", api: api.status },
    { headers: { "Cache-Control": "no-store" } },
  );
}
