import type { CouncilOut } from "@approvalready/shared-types";
import { render, screen } from "@testing-library/react";

import { CouncilGuide } from "./CouncilGuide";

function council(overrides: Partial<CouncilOut> = {}): CouncilOut {
  return {
    key: "testshire",
    name: "Test Shire Council",
    spatial_name: "Test Shire",
    checked_on: "2026-10-11",
    checked: { verified: false, verified_at: null },
    website: "https://testshire.example",
    planning_url: "https://testshire.example/da",
    planning_scheme: { name: "Test Planning Scheme 2020", url: "https://testshire.example/ps" },
    lodgement: [
      { method: "ONLINE", label: "Lodge online", url: "https://testshire.example/portal", email: null, address: null },
      { method: "EMAIL", label: "Email your application", url: null, email: "planning@testshire.example", address: null },
    ],
    steps: ["Book a pre-lodgement meeting.", "Lodge with DA Form 1."],
    pre_lodgement: { available: true, url: null, note: "Free for 30 minutes." },
    contact: { phone: "07 4000 0000", email: "mail@testshire.example", address: "1 Main St", hours: null },
    fees: {
      schedule_url: "https://testshire.example/fees.pdf",
      fee_year: "2026-27",
      items: [{ label: "Dwelling house (code)", amount: "$1,000.00", note: null }],
    },
    sources: [{ url: "https://testshire.example/da", title: "Development applications" }],
    gaps: ["Office hours not published."],
    general_steps: ["Check the planning scheme."],
    general_source: { url: "https://planning.example/process", title: "Process" },
    ...overrides,
  } as CouncilOut;
}

describe("CouncilGuide", () => {
  it("shows how to lodge, steps, fees and contacts, labelled as not yet checked", () => {
    render(<CouncilGuide council={council()} />);
    expect(screen.getByRole("heading", { name: "How to apply to Test Shire Council" })).toBeInTheDocument();
    expect(screen.getByText("Not yet checked by our team")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Lodge online" })).toHaveAttribute(
      "href",
      "https://testshire.example/portal",
    );
    expect(screen.getByRole("link", { name: "planning@testshire.example" })).toHaveAttribute(
      "href",
      "mailto:planning@testshire.example",
    );
    expect(screen.getByText("Lodge with DA Form 1.")).toBeInTheDocument();
    expect(screen.getByText("$1,000.00")).toBeInTheDocument();
    expect(screen.getByText(/2026-27 fees/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "07 4000 0000" })).toHaveAttribute(
      "href",
      "tel:+61740000000",
    );
    expect(screen.getByText("Office hours not published.")).toBeInTheDocument();
  });

  it("says to check with council when no fees are published and uses the state's steps", () => {
    render(<CouncilGuide council={council({ fees: null, steps: [] })} />);
    expect(screen.getByText(/Check with the council/)).toBeInTheDocument();
    expect(screen.getByText("Check the planning scheme.")).toBeInTheDocument();
    expect(screen.getByText(/doesn't publish its own steps online/)).toBeInTheDocument();
  });

  it("shows when our team has checked the details", () => {
    render(
      <CouncilGuide
        council={council({ checked: { verified: true, verified_at: "2026-10-20T01:00:00Z" } })}
      />,
    );
    expect(screen.getByText(/Checked by our team/)).toBeInTheDocument();
    expect(screen.queryByText(/Confirm the details/)).not.toBeInTheDocument();
  });
});
