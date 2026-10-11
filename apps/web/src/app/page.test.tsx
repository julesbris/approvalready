import { render, screen, within } from "@testing-library/react";

import HomePage from "./page";

describe("HomePage", () => {
  it("presents all seven product areas as one platform", () => {
    render(<HomePage />);
    const list = screen.getByRole("list", { name: "Product areas" });
    const names = within(list)
      .getAllByRole("heading", { level: 3 })
      .map((h) => h.textContent);
    expect(names).toEqual([
      "PlanningReady",
      "VesselReady",
      "BusinessReady",
      "GrantReady",
      "SellReady",
      "RentReady",
      "TradeReady",
    ]);
  });

  it("links each product area to a new project in that area", () => {
    render(<HomePage />);
    const list = screen.getByRole("list", { name: "Product areas" });
    expect(within(list).getByRole("link", { name: /PlanningReady/ })).toHaveAttribute(
      "href",
      "/projects/new?vertical=PLANNING",
    );
    expect(within(list).getAllByRole("link")).toHaveLength(7);
  });

  it("keeps the guides and sign in reachable from the small-screen menu", () => {
    render(<HomePage />);
    const menu = screen.getByRole("navigation", { name: "Menu" });
    expect(within(menu).getByRole("link", { name: "Guides" })).toHaveAttribute("href", "/guides");
    expect(within(menu).getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
  });

  it("states the confidence model and the advice limitation", () => {
    render(<HomePage />);
    expect(screen.getByText(/verified, likely, review required, or unknown/i)).toBeInTheDocument();
    expect(screen.getByText(/not legal, financial or planning advice/i)).toBeInTheDocument();
  });

  it("does not lead with a marketplace or paid-leads message", () => {
    const { container } = render(<HomePage />);
    expect(container.textContent).not.toMatch(/pay us for leads|marketplace/i);
  });
});
