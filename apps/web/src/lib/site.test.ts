import { describe, expect, it } from "vitest";

import { NONCE_CSP_PATHS } from "@/lib/csp";
import { PRIVATE_PATHS, siteUrl, sitemapPaths } from "@/lib/site";

describe("site", () => {
  it("prefers the configured address", () => {
    expect(siteUrl("https://approvalready.au/", "app.approvalready.au")).toBe(
      "https://approvalready.au",
    );
    expect(siteUrl(undefined, "approvalready.au")).toBe("https://approvalready.au");
  });

  it("lists the public pages and no signed-in ones", () => {
    const paths = sitemapPaths();
    expect(paths).toEqual(
      expect.arrayContaining(["/", "/guides", "/privacy", "/terms", "/contact"]),
    );
    for (const path of paths) {
      expect(PRIVATE_PATHS.some((p) => path.startsWith(p))).toBe(false);
    }
  });

  it("keeps the signed-in areas out of search", () => {
    for (const area of ["/account", "/admin", "/projects", "/partner", "/review"]) {
      expect(NONCE_CSP_PATHS).toContain(area);
      expect(PRIVATE_PATHS).toContain(area);
    }
  });
});
