import { render, screen, within } from "@testing-library/react";

import { GUIDES } from "@/lib/guides";
import { GUIDE_STATES } from "@/lib/publicGuides";

import GuidesPage from "./page";

describe("GuidesPage", () => {
  it("lists every explainer as one link to it", () => {
    render(<GuidesPage />);
    const list = screen.getByRole("list", { name: "Explainers" });
    const links = within(list).getAllByRole("link");
    expect(links.map((a) => a.getAttribute("href"))).toEqual(
      GUIDES.map((g) => `/guides/${g.slug}`),
    );
    const [first] = GUIDES;
    expect(within(list).getByRole("heading", { name: first?.title, level: 3 })).toBeInTheDocument();
  });

  it("links to every state's guides", () => {
    render(<GuidesPage />);
    for (const state of GUIDE_STATES) {
      const heading = screen.getByRole("heading", { name: state.name, level: 3 });
      expect(heading.closest("a")).toHaveAttribute(
        "href",
        `/guides/${state.segment}`,
      );
    }
  });
});
