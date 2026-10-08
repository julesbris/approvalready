import { nonceCsp, staticCsp, usesNonceCsp } from "./csp";

describe("CSP", () => {
  it("nonce policy has no unsafe-inline scripts in production", () => {
    const csp = nonceCsp("abc", false);
    const script = csp.split("; ").find((d) => d.startsWith("script-src"));
    expect(script).toBe("script-src 'self' 'nonce-abc' 'strict-dynamic'");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("object-src 'none'");
  });

  it("static policy never allows eval in production", () => {
    expect(staticCsp(false)).not.toContain("unsafe-eval");
  });

  it.each([
    ["/login", true],
    ["/account", true],
    ["/invitations/accept", true],
    ["/projects", true],
    ["/projects/abc/questionnaire", true],
    ["/admin", true],
    ["/admin/rules/versions/abc", true],
    ["/administration-guide", false],
    ["/projectsx", false],
    ["/", false],
    ["/planning", false],
    ["/accounting-guide", false],
  ])("%s uses nonce CSP: %s", (path, expected) => {
    expect(usesNonceCsp(path)).toBe(expected);
  });
});
