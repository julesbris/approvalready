import { hashesFor, nonceCsp, parseHashManifest, staticCsp, usesNonceCsp } from "./csp";

describe("CSP", () => {
  it("nonce policy has no unsafe-inline scripts in production", () => {
    const csp = nonceCsp("abc", false);
    const script = csp.split("; ").find((d) => d.startsWith("script-src"));
    expect(script).toBe("script-src 'self' 'nonce-abc' 'strict-dynamic'");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("object-src 'none'");
  });

  it("static policy allows only the build's inline scripts in production", () => {
    const csp = staticCsp(false, ["'sha256-abc='", "'sha256-def='"]);
    const script = csp.split("; ").find((d) => d.startsWith("script-src"));
    expect(script).toBe("script-src 'self' 'sha256-abc=' 'sha256-def='");
    expect(csp).not.toContain("unsafe-eval");
    expect(csp).toContain("frame-ancestors 'none'");
  });

  it("static policy without a manifest allows no inline scripts", () => {
    const script = staticCsp(false, []).split("; ").find((d) => d.startsWith("script-src"));
    expect(script).toBe("script-src 'self'");
  });

  it("development keeps inline scripts and eval for hot reload", () => {
    expect(staticCsp(true, [])).toContain("'unsafe-inline' 'unsafe-eval'");
  });

  it("reads only well-formed hashes from the manifest", () => {
    const raw = JSON.stringify({
      scriptHashes: ["'sha256-AbC+/9='", "'unsafe-inline'", "sha256-noquotes", 7],
    });
    expect(parseHashManifest(raw).fallback).toEqual(["'sha256-AbC+/9='"]);
    expect(parseHashManifest("{}").fallback).toEqual([]);
  });

  it("gives each prerendered page only its own hashes", () => {
    const manifest = parseHashManifest(
      JSON.stringify({
        scriptHashes: ["'sha256-shared='"],
        pages: { "/guides/nsw": ["'sha256-nsw='", "nope"], "/": ["'sha256-home='"] },
      }),
    );
    expect(hashesFor(manifest, "/guides/nsw")).toEqual(["'sha256-nsw='"]);
    expect(hashesFor(manifest, "/guides/nsw/")).toEqual(["'sha256-nsw='"]);
    expect(hashesFor(manifest, "/")).toEqual(["'sha256-home='"]);
    expect(hashesFor(manifest, "/guides/missing")).toEqual(["'sha256-shared='"]);
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
    ["/review", true],
    ["/review/abc", true],
    ["/reviews-of-us", false],
    ["/partner", true],
    ["/partner/profile", true],
    ["/unsubscribe", true],
    ["/projectsx", false],
    ["/", false],
    ["/planning", false],
    ["/accounting-guide", false],
  ])("%s uses nonce CSP: %s", (path, expected) => {
    expect(usesNonceCsp(path)).toBe(expected);
  });
});
