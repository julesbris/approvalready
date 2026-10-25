import { VERTICALS } from "@approvalready/shared-types";
import { render, screen } from "@testing-library/react";

import FinancePage from "@/app/finance/page";
import { FINANCE_ENQUIRY_URL, FINANCE_OFFER, financeOffer } from "@/lib/finance";

import { FinanceCallout } from "./FinanceCallout";

describe("FinanceCallout", () => {
  it("sends the enquiry to the finance contact form in a new tab", () => {
    render(<FinanceCallout vertical="VESSEL" />);
    expect(screen.getByRole("heading", { name: "Need finance for a vessel?" })).toBeVisible();
    const enquiry = screen.getByRole("link", { name: "Make a finance enquiry" });
    expect(enquiry).toHaveAttribute("href", FINANCE_ENQUIRY_URL);
    expect(enquiry).toHaveAttribute("target", "_blank");
    expect(enquiry).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByRole("link", { name: "See all finance options" })).toHaveAttribute(
      "href",
      "/finance",
    );
  });

  it("has wording for every project area and a headline offer otherwise", () => {
    for (const vertical of VERTICALS) {
      expect(financeOffer(vertical)).not.toBe(FINANCE_OFFER);
    }
    expect(financeOffer(undefined)).toBe(FINANCE_OFFER);
    expect(financeOffer("SOMETHING_NEW")).toBe(FINANCE_OFFER);
  });
});

describe("FinancePage", () => {
  it("lists mortgages and asset finance and links to the enquiry form", () => {
    render(<FinancePage />);
    expect(screen.getByRole("heading", { name: "Home loans and mortgages" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Asset finance" })).toBeVisible();
    const links = screen.getAllByRole("link", { name: "Make a finance enquiry" });
    expect(links.length).toBeGreaterThan(0);
    for (const link of links) expect(link).toHaveAttribute("href", FINANCE_ENQUIRY_URL);
    expect(screen.queryByRole("link", { name: "See all finance options" })).toBeNull();
  });
});
