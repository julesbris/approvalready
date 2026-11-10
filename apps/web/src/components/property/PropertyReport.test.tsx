import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  distanceWords,
  monthlyRepayment,
  PropertyReport,
} from "./PropertyReport";

const REPORT = {
  property_id: "p1",
  address: "34 Gilmore Street, Bentley Park QLD 4869",
  suburb: "Bentley Park",
  council: "Cairns Regional Council",
  headline: ["In the catchment for Bentley Park State School."],
  scores: [
    {
      key: "walk",
      label: "Walk to everyday needs",
      score: 7.5,
      summary: "6 of 8 within 800 m.",
    },
    {
      key: "quiet",
      label: "Quiet streets",
      score: 8,
      summary: "Nearby: major road 150 m.",
    },
  ],
  overall_score: 7.8,
  finance_url: "https://approvalreadyai.com/#contact",
  generated_at: "2026-10-12T00:00:00Z",
  disclaimer: "General information only.",
  sections: [
    {
      key: "people",
      title: "Who lives in Bentley Park",
      intro: "The suburb at the 2021 Census.",
      status: "ok",
      facts: [
        {
          label: "Median household income",
          value: "$1,500 a week",
          compare: "10% below Queensland ($1,675)",
          note: null,
        },
      ],
      items: [
        {
          label: "Supermarket",
          detail: "Nearest: Woolworths",
          distance_m: 1240,
          url: null,
        },
      ],
      links: [
        {
          label: "Census QuickStats",
          url: "https://abs.gov.au/x",
          why: "More.",
        },
      ],
      sources: [
        {
          name: "ABS Census 2021",
          url: "https://abs.gov.au/x",
          as_at: "Census 2021",
        },
      ],
      charts: [
        {
          title: "Homes owned and rented",
          compare_label: "Queensland",
          bars: [{ label: "Rented", value: 37.5, compare: 33.1 }],
        },
      ],
    },
    {
      key: "market",
      title: "Prices, rent and mortgages",
      intro: "What people pay.",
      status: "ok",
      facts: [],
      items: [],
      links: [],
      sources: [],
      charts: [],
    },
    {
      key: "safety",
      title: "Reported crime",
      intro: "Offences.",
      status: "unavailable",
      facts: [],
      items: [],
      links: [],
      sources: [],
    },
  ],
};

afterEach(() => vi.unstubAllGlobals());

describe("PropertyReport", () => {
  it("shows each section with its figures, sources and the PDF link", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(REPORT)));
    render(<PropertyReport organisationId="o1" propertyId="p1" />);
    expect(screen.getByRole("status")).toHaveTextContent("Gathering");
    expect(await screen.findByText("$1,500 a week")).toBeInTheDocument();
    expect(screen.getByText(/10% below Queensland/)).toBeInTheDocument();
    expect(screen.getByText("1.2 km")).toBeInTheDocument();
    expect(
      screen.getByText(/couldn't check this just now/),
    ).toBeInTheDocument();
    expect(screen.getByText("7.8")).toBeInTheDocument();
    expect(screen.getByText("Walk to everyday needs")).toBeInTheDocument();
    expect(screen.getByText("Nearby: major road 150 m.")).toBeInTheDocument();
    expect(screen.getByText(/\(Queensland 33.1%\)/)).toBeInTheDocument();
    // $600,000 over 30 years at 6%.
    expect(screen.getByText("$3,597 a month")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Make a finance enquiry" }),
    ).toHaveAttribute("href", "https://approvalreadyai.com/#contact");
    expect(screen.getByRole("link", { name: "Download PDF" })).toHaveAttribute(
      "href",
      "/api/v1/organisations/o1/properties/p1/report.pdf",
    );
  });

  it("works out monthly repayments", () => {
    expect(Math.round(monthlyRepayment(600000, 6, 30))).toBe(3597);
    expect(monthlyRepayment(120000, 0, 10)).toBe(1000);
    expect(monthlyRepayment(0, 6, 30)).toBe(0);
  });

  it("words distances", () => {
    expect(distanceWords(64)).toBe("60 m");
    expect(distanceWords(2345)).toBe("2.3 km");
  });
});
