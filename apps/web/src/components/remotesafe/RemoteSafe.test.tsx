import type { RemoteSafeDashboardOut } from "@approvalready/shared-types";
import { render, screen } from "@testing-library/react";

import { DashboardSummary, JourneyList } from "./RemoteSafeHome";

const DASHBOARD = {
  scope: "organisation",
  by_status: { SUBMITTED: 1 },
  by_outcome: { HIGH: 1 },
  awaiting_my_approval: 1,
  active: 0,
  critical_control_failures: 0,
  repeated_hazards: [],
  completion_rate: null,
  upcoming: [],
  monitoring_live: false,
} as unknown as RemoteSafeDashboardOut;

describe("RemoteSafe home", () => {
  it("says plainly that check-in monitoring is not live", () => {
    render(<DashboardSummary d={DASHBOARD} />);
    expect(screen.getByText(/Check-in monitoring isn.t live yet/)).toBeInTheDocument();
    expect(screen.getByText("Waiting for my approval")).toBeInTheDocument();
  });

  it("lists journeys with status and risk", () => {
    render(
      <JourneyList
        title="My journeys"
        empty="No journeys yet."
        journeys={[
          {
            id: "j1",
            reference: "RS-ABC234",
            title: "Cooktown to Coen",
            status: "SUBMITTED",
            revision: 1,
            risk_outcome: "HIGH",
            worker: { user_id: "u1", display_name: "Sam" },
            supervisor: null,
            origin: "Cooktown",
            destination: "Coen",
            departs: { utc: "2026-11-23T20:00:00Z", local: "Tue 24 Nov 2026, 06:00 AEST", timezone: "Australia/Brisbane" },
            arrives: { utc: "2026-11-24T03:00:00Z", local: "Tue 24 Nov 2026, 13:00 AEST", timezone: "Australia/Brisbane" },
            archived: false,
            updated_at: "2026-11-21T00:00:00Z",
          },
        ]}
      />,
    );
    expect(screen.getByRole("link", { name: "Cooktown to Coen" })).toHaveAttribute(
      "href",
      "/remotesafe/journeys/j1",
    );
    expect(screen.getByText("Waiting for approval")).toBeInTheDocument();
    expect(screen.getByText("High risk")).toBeInTheDocument();
  });
});
