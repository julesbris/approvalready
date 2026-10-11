import { render, screen, within } from "@testing-library/react";

import { GUIDES } from "@/lib/guides";

import GuidesPage from "./page";

describe("GuidesPage", () => {
  it("lists every guide as one link to it", () => {
    render(<GuidesPage />);
    const list = screen.getByRole("list", { name: "Guides" });
    const links = within(list).getAllByRole("link");
    expect(links.map((a) => a.getAttribute("href"))).toEqual(
      GUIDES.map((g) => `/guides/${g.slug}`),
    );
    const [first] = GUIDES;
    expect(within(list).getByRole("heading", { name: first?.title, level: 2 })).toBeInTheDocument();
  });
});
