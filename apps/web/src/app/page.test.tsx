import { render, screen, within } from "@testing-library/react";

import HomePage from "./page";

describe("HomePage", () => {
  it("presents all six product areas as one platform", () => {
    render(<HomePage />);
    const list = screen.getByRole("list", { name: "Product areas" });
    const names = within(list)
      .getAllByRole("heading", { level: 2 })
      .map((h) => h.textContent);
    expect(names).toEqual([
      "PlanningReady",
      "VesselReady",
      "BusinessReady",
      "GrantReady",
      "SellReady",
      "RentReady",
    ]);
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
