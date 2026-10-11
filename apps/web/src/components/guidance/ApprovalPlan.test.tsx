import type { ApprovalGuideOut } from "@approvalready/shared-types";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ApprovalPlan } from "./ApprovalPlan";

function guide(overrides: Partial<ApprovalGuideOut> = {}): ApprovalGuideOut {
  return {
    kind: "VEHICLE_IMPORT_APPROVAL",
    title: "Vehicle import approval",
    summary: "You need an approval before the car is shipped.",
    authority: "Department of Infrastructure",
    publisher: "Department of Infrastructure",
    verticals: ["TRADE"],
    jurisdiction: "CTH",
    order: 400,
    checked_on: "2026-10-11",
    timeframe: "Up to 30 business days",
    cost_summary: "A$42.20 for an older vehicle",
    before_you_start: ["Find the build date."],
    steps: [
      {
        title: "Lodge in ROVER",
        detail: "Apply online and upload photos.",
        timeframe: "1 to 2 hours",
        cost: "A$42.20",
        form: { name: "Single Road Vehicle Approval", url: "https://rover.example.gov.au" },
        url: "https://example.gov.au/step",
      },
    ],
    fees: [{ label: "Older vehicle", amount: "A$42.20", note: "Passenger car" }],
    contacts: [
      {
        name: "Vehicle imports",
        phone: "1800 075 001",
        email: null,
        url: null,
        hours: null,
        note: null,
      },
    ],
    watch_out: ["Don't ship before approval."],
    sources: [{ url: "https://example.gov.au/source", title: "8 steps to importing a vehicle" }],
    gaps: ["Phone number not confirmed."],
    checked: { verified: false, verified_at: null },
    ...overrides,
  };
}

describe("ApprovalPlan", () => {
  it("renders nothing without guides", () => {
    const { container } = render(<ApprovalPlan guides={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("lists every approval in order with steps, fees, contacts and gaps", () => {
    render(
      <ApprovalPlan
        guides={[
          guide(),
          guide({
            kind: "QLD_VEHICLE_REGISTRATION",
            title: "Registering in Queensland",
            order: 480,
            timeframe: null,
            cost_summary: null,
            checked: { verified: true, verified_at: "2026-10-12T00:00:00Z" },
          }),
        ]}
      />,
    );
    expect(screen.getByRole("heading", { name: "Your step-by-step plan" })).toBeInTheDocument();
    const overview = screen.getByRole("table", { name: "" });
    const rows = within(overview).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("1. Vehicle import approval");
    expect(rows[1]).toHaveTextContent("Up to 30 business days");
    expect(rows[2]).toHaveTextContent("2. Registering in Queensland");
    expect(rows[2]).toHaveTextContent("See steps");

    const first = within(document.getElementById("guide-vehicle_import_approval") as HTMLElement);
    expect(first.getByText("Lodge in ROVER")).toBeInTheDocument();
    expect(first.getByRole("link", { name: "Single Road Vehicle Approval" })).toHaveAttribute(
      "href",
      "https://rover.example.gov.au",
    );
    expect(first.getByRole("link", { name: "1800 075 001" })).toHaveAttribute(
      "href",
      "tel:1800075001",
    );
    expect(first.getByText("Don't ship before approval.")).toBeInTheDocument();
    expect(first.getByText("Phone number not confirmed.")).toBeInTheDocument();
    expect(screen.getAllByText("Not yet checked by our team")).toHaveLength(1);
    expect(screen.getByText(/Checked by our team/)).toBeInTheDocument();
  });
});
