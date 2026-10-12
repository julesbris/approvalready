import { readFileSync } from "node:fs";
import path from "node:path";

import {
  cardAlt,
  cardPath,
  guideFaqs,
  guideJsonLd,
  jsonLdScript,
  metaDescription,
  pageTitle,
  PUBLIC_GUIDES,
  publicGuide,
} from "@/lib/publicGuides";
import { sitemapPaths } from "@/lib/site";

const guides = JSON.parse(
  readFileSync(
    path.resolve(__dirname, "../../../api/app/modules/guidance/approval_guides.json"),
    "utf8",
  ),
) as { guides: { kind: string }[] };

describe("public guide pages", () => {
  it("gives every guide its own page", () => {
    expect(PUBLIC_GUIDES).toHaveLength(guides.guides.length);
    const paths = PUBLIC_GUIDES.map((g) => g.path);
    expect(new Set(paths).size).toBe(paths.length);
    expect(publicGuide("nsw", "boat-licence")?.kind).toBe("NSW_BOAT_LICENCE");
    expect(publicGuide("australia", "abn-registration")?.state.name).toBe("Australia-wide");
  });

  it("writes titles and descriptions for search results", () => {
    for (const g of PUBLIC_GUIDES) {
      expect(metaDescription(g).length).toBeLessThanOrEqual(160);
      expect(pageTitle(g).length).toBeGreaterThan(10);
    }
    const titles = PUBLIC_GUIDES.map(pageTitle);
    expect(new Set(titles).size).toBe(titles.length);
    const nsw = publicGuide("nsw", "boat-licence");
    expect(nsw && pageTitle(nsw)).toBe("General boat licence (NSW)");
  });

  it("answers the questions people ask from the guide's own text", () => {
    const g = publicGuide("nsw", "pool-compliance-certificate");
    expect(g).toBeDefined();
    if (!g) return;
    const faqs = guideFaqs(g);
    expect(faqs.map((f) => f.question)).toEqual(
      expect.arrayContaining(["How much does it cost?", "Which forms do I need?"]),
    );
    expect(faqs[0]?.answer).toBe(g.summary);
  });

  it("describes the page for search and answer engines", () => {
    const g = publicGuide("nsw", "pool-compliance-certificate");
    if (!g) throw new Error("missing guide");
    const data = guideJsonLd(g, "https://approvalready.au") as { "@graph": { "@type": string }[] };
    expect(data["@graph"].map((n) => n["@type"])).toEqual([
      "Article",
      "HowTo",
      "FAQPage",
      "BreadcrumbList",
      "Organization",
    ]);
    expect(jsonLdScript({ a: "</script>" })).not.toContain("</script>");
    expect(cardPath(g, "wide")).toBe("/guide-cards/approval-nsw-pool-compliance-certificate.wide.jpg");
    expect(cardAlt(g)).toContain("New South Wales");
  });

  it("puts every guide and state page in the sitemap", () => {
    const paths = sitemapPaths();
    expect(paths).toContain("/guides/nsw");
    expect(paths).toContain("/guides/nsw/boat-licence");
  });
});
