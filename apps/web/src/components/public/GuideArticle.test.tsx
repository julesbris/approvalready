import { render, screen, within } from "@testing-library/react";

import { GUIDES, guide } from "@/lib/guides";

import { GuideArticle } from "./GuideArticle";

describe("guides", () => {
  it("cite official sources and say how far they've been checked", () => {
    expect(GUIDES.length).toBeGreaterThan(0);
    for (const g of GUIDES) {
      expect(g.sources.length).toBeGreaterThan(0);
      for (const s of g.sources) {
        expect(s.url).toMatch(/^https:\/\/(www\.)?(cairns|planning|legislation)\.qld\.gov\.au\//);
        expect(s.version).not.toBe("");
      }
      expect(g.notCovered.length).toBeGreaterThan(0);
      expect(new Set(GUIDES.map((x) => x.slug)).size).toBe(GUIDES.length);
    }
  });

  it("renders a guide with its status, limits and sources", () => {
    const g = guide("cairns-secondary-dwellings");
    expect(g).toBeDefined();
    render(<GuideArticle guide={g!} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(g!.title);
    expect(screen.getByText(/has not yet verified them/)).toBeInTheDocument();
    expect(screen.getByText(/not legal or planning advice/)).toBeInTheDocument();
    const sources = screen.getByRole("region", { name: "Sources" });
    expect(within(sources).getAllByRole("link")).toHaveLength(g!.sources.length);
    expect(screen.getByRole("heading", { name: "What this guide doesn't cover" })).toBeVisible();
  });
});
