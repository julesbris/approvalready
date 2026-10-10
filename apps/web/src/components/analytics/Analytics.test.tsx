import type { BenchmarksOut, FunnelOut } from "@approvalready/shared-types";
import { render, screen, within } from "@testing-library/react";

import { BenchmarkTable, Stats, partnerStats } from "./Analytics";

const FUNNEL: FunnelOut = {
  offered: 4,
  accepted: 2,
  declined: 1,
  missed: 1,
  waiting: 0,
  in_progress: 1,
  quoted: 1,
  won: 1,
  lost: 0,
  accept_rate: 0.5,
  win_rate: 1,
  answered_within_48h_rate: 0.75,
  median_response_hours: 2.5,
  included: 1,
  fees_cents: 2500,
  refunded_cents: 0,
};

describe("analytics components", () => {
  it("shows a partner's headline figures", () => {
    render(<Stats items={partnerStats(FUNNEL)} />);
    expect(screen.getByText("Accepted").nextSibling).toHaveTextContent("2 (50%)");
    expect(screen.getByText("Typical reply time").nextSibling).toHaveTextContent("2.5 hours");
    expect(screen.getByText("Fees paid").nextSibling).toHaveTextContent("$25.00");
  });

  it("withholds other partners' figures below the threshold", () => {
    const bench: BenchmarksOut = {
      min_partners: 5,
      rows: [
        {
          category_key: null,
          category_label: "All categories",
          accept_rate: 0.4,
          win_rate: null,
          median_response_hours: 6,
          withheld: false,
        },
        {
          category_key: "town_planner",
          category_label: "Town planner",
          accept_rate: null,
          win_rate: null,
          median_response_hours: null,
          withheld: true,
        },
      ],
    };
    const mine = new Map([
      ["", FUNNEL],
      ["town_planner", FUNNEL],
    ]);
    render(<BenchmarkTable mine={mine} bench={bench} />);
    expect(screen.getByText(/at least 5 other partners/)).toBeInTheDocument();
    const all = screen.getByRole("row", { name: /All categories/ });
    expect(all).toHaveTextContent("50% / 40%");
    expect(all).toHaveTextContent("2.5 hours / 6 hours");
    const planner = screen.getByRole("row", { name: /Town planner/ });
    expect(within(planner).getAllByText("not enough partners yet")).toHaveLength(3);
  });
});
