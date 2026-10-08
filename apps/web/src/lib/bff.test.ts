import { buildUpstreamHeaders, isProxiedPath } from "./bff";

describe("isProxiedPath", () => {
  it.each([
    [["auth", "login"], true],
    [["organisations", "abc", "members"], true],
    [["invitations", "accept"], true],
    [["admin", "audit", "verify"], true],
    [["questionnaires", "planning.general"], true],
    [["health", "ready"], false],
    [["internal", "tls"], false],
    [[], false],
    [["auth", "..", "health"], false],
    [["auth", ""], false],
  ])("%j -> %s", (path, expected) => {
    expect(isProxiedPath(path)).toBe(expected);
  });
});

describe("buildUpstreamHeaders", () => {
  it("forwards only allowlisted headers", () => {
    const incoming = new Headers({
      cookie: "ar_session=abc",
      "x-csrf-token": "t",
      "content-type": "application/json",
      authorization: "Bearer stolen",
      host: "app.example",
      "x-forwarded-for": "203.0.113.9",
    });
    const out = buildUpstreamHeaders(incoming);
    expect(out.get("cookie")).toBe("ar_session=abc");
    expect(out.get("x-csrf-token")).toBe("t");
    expect(out.get("x-forwarded-for")).toBe("203.0.113.9");
    expect(out.get("authorization")).toBeNull();
    expect(out.get("host")).toBeNull();
  });
});
