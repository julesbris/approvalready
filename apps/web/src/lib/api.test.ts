import { probeApi } from "./api";

const ready = { status: "ok", checks: { database: { status: "ok", latency_ms: 1 } } };

function fakeFetch(status: number, body: unknown): typeof fetch {
  return (async () => new Response(JSON.stringify(body), { status })) as typeof fetch;
}

describe("probeApi", () => {
  it("reports ok when the API is ready", async () => {
    expect((await probeApi(fakeFetch(200, ready))).status).toBe("ok");
  });

  it("reports degraded when the API returns 503", async () => {
    const result = await probeApi(fakeFetch(503, { ...ready, status: "error" }));
    expect(result.status).toBe("degraded");
  });

  it("reports unreachable on network failure", async () => {
    const failing = (async () => {
      throw new TypeError("fetch failed");
    }) as typeof fetch;
    expect((await probeApi(failing)).status).toBe("unreachable");
  });
});
