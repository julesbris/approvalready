import type { CustomerQuoteOut } from "@approvalready/shared-types";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { CustomerQuotes } from "./CustomerQuotes";
import { QuoteForm } from "./QuoteActions";

const apiRequest = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));
vi.mock("@/lib/client-api", () => ({
  apiRequest: (...args: unknown[]) => apiRequest(...args),
}));

function quote(overrides: Partial<CustomerQuoteOut>): CustomerQuoteOut {
  return {
    id: "q1",
    lead_id: "lead1",
    version: 1,
    status: "SENT",
    expired: false,
    title: "Development application",
    scope: "Prepare and lodge the DA.",
    line_items: [{ description: "Planning report", amount_cents: 250000 }],
    total_cents: 250000,
    gst: "EXCLUDED",
    gst_cents: 25000,
    total_inc_gst_cents: 275000,
    valid_until: "2026-11-09",
    start_estimate: "Within two weeks",
    terms: null,
    sent_at: "2026-10-10T01:00:00Z",
    responded_at: null,
    response_note: null,
    category_key: "town_planner",
    category_label: "Town planner",
    partner: { name: "Reef Planning", phone: null, contact_email: null, website: null },
    ...overrides,
  };
}

describe("CustomerQuotes", () => {
  beforeEach(() => apiRequest.mockReset());

  it("compares quotes for a job and offers to decline the others on accepting", async () => {
    apiRequest.mockResolvedValue({ ok: true, data: [] });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(
      <CustomerQuotes
        organisationId="org"
        projectId="p"
        canWrite
        quotes={[
          quote({}),
          quote({
            id: "q2",
            partner: {
              name: "Tableland Planning",
              phone: null,
              contact_email: null,
              website: null,
            },
            total_inc_gst_cents: 199000,
            gst: "NOT_REGISTERED",
            gst_cents: 0,
          }),
        ]}
      />,
    );
    expect(screen.getByRole("heading", { name: "Town planner" })).toBeInTheDocument();
    expect(screen.getAllByText("$2,750.00").length).toBeGreaterThan(0);
    expect(screen.getAllByText("$1,990.00").length).toBeGreaterThan(0);
    fireEvent.click(screen.getAllByRole("button", { name: "Accept quote" })[0]!);
    await waitFor(() => expect(apiRequest).toHaveBeenCalled());
    expect(apiRequest).toHaveBeenCalledWith(
      "POST",
      "/organisations/org/projects/p/quotes/q1/accept",
      {
        decline_others: true,
        note: null,
      },
    );
    expect(confirm).toHaveBeenCalledTimes(2);
    confirm.mockRestore();
  });

  it("doesn't offer to accept an expired quote", () => {
    render(
      <CustomerQuotes
        organisationId="org"
        projectId="p"
        canWrite
        quotes={[quote({ expired: true })]}
      />,
    );
    expect(screen.queryByRole("button", { name: "Accept quote" })).toBeNull();
    expect(screen.getByRole("button", { name: "Decline" })).toBeInTheDocument();
    expect(screen.getAllByText("Expired").length).toBeGreaterThan(0);
  });
});

describe("QuoteForm", () => {
  it("shows the total with GST as the partner types", () => {
    render(<QuoteForm organisationId="org" matchId="m" revising={null} />);
    fireEvent.click(screen.getByRole("button", { name: "Send a quote" }));
    fireEvent.change(screen.getByLabelText("Amount ($)"), { target: { value: "1,100" } });
    expect(screen.getByText("Total $1,100.00")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("GST"), { target: { value: "EXCLUDED" } });
    expect(screen.getByText("Total $1,210.00")).toBeInTheDocument();
  });
});
