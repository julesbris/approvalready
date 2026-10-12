import type { PlanSectionOut, PlanStepOut, ProjectPlanOut } from "@approvalready/shared-types";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { PlanOffer } from "./PlanOffer";
import { ProjectPlan } from "./ProjectPlan";

const apiRequest = vi.fn();
const refresh = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh }),
}));
vi.mock("@/lib/client-api", () => ({
  apiRequest: (...args: unknown[]) => apiRequest(...args),
}));

const OFFER = {
  on_sale: false,
  price_cents: null,
  currency: null,
  product_name: "Project plan",
  product_description: "Manage one project online.",
  included_in_membership: false,
  membership_on_sale: false,
};

function step(overrides: Partial<PlanStepOut>): PlanStepOut {
  return {
    id: "s1",
    section_key: "approval:LIQUOR_LICENCE",
    position: 1,
    kind: "STEP",
    title: "Lodge the application",
    detail: "Online through the portal.",
    timeframe: "About 8 weeks",
    cost: "$1,200",
    link_url: "https://example.gov.au/apply",
    link_label: "Application form",
    owner: "You",
    assignee_user_id: null,
    due_on: "2026-11-02",
    status: "OPEN",
    completed_at: null,
    note: null,
    documents: [],
    partner: null,
    editable: false,
    ...overrides,
  };
}

function section(overrides: Partial<PlanSectionOut>): PlanSectionOut {
  return {
    key: "approval:LIQUOR_LICENCE",
    kind: "APPROVAL",
    title: "Get a liquor licence",
    authority: "Office of Liquor and Gaming Regulation",
    summary: null,
    certainty_label: "Required",
    timeframe: null,
    cost_summary: null,
    fees: [{ label: "Application fee", amount: "$1,200", note: null }],
    contacts: [],
    watch_out: [],
    sources: [],
    gaps: [],
    checked_on: null,
    verified: false,
    help: [
      {
        key: "liquor_licensing_consultant",
        label: "Liquor licensing consultant",
        description: "Helps with liquor licences.",
        introduction_open: false,
        partners: [
          {
            id: "p1",
            name: "Reef Licensing",
            phone: "07 4000 0000",
            email: "hello@reef.example.com.au",
            website: "reef.example.com.au",
            description: null,
            why: "Works in your council area",
            introduced: false,
          },
        ],
      },
    ],
    steps: [step({})],
    done: 0,
    total: 1,
    starts_on: "2026-11-02",
    ends_on: "2026-11-02",
    ...overrides,
  };
}

function plan(): ProjectPlanOut {
  return {
    status: "ACTIVE",
    offer: OFFER,
    id: "plan1",
    assessment_id: "a1",
    starts_on: "2026-10-11",
    activated_at: "2026-10-11T00:00:00Z",
    complimentary: true,
    progress: {
      total: 1,
      done: 0,
      percent: 0,
      overdue: 0,
      due_this_week: 0,
      next_item_id: "s1",
      finish_on: "2026-11-02",
    },
    sections: [section({})],
  };
}

describe("ProjectPlan", () => {
  beforeEach(() => apiRequest.mockReset());

  it("shows the timeline, the partners to call and ticks steps off", async () => {
    apiRequest.mockResolvedValue({
      ok: true,
      data: step({ status: "DONE", completed_at: "2026-10-12T00:00:00Z" }),
    });
    render(
      <ProjectPlan
        organisationId="org"
        projectId="p"
        assessmentId="a1"
        plan={plan()}
        documents={[]}
        canWrite
      />,
    );
    expect(screen.getByRole("heading", { name: "Timeline" })).toBeInTheDocument();
    expect(screen.getByText("0 of 1 steps done (0%)")).toBeInTheDocument();
    expect(screen.getByText("Reef Licensing")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "07 4000 0000" })).toHaveAttribute(
      "href",
      "tel:+61740000000",
    );
    expect(screen.getByRole("link", { name: "Website" })).toHaveAttribute(
      "href",
      "https://reef.example.com.au",
    );
    expect(screen.getByRole("link", { name: "Ask for introductions" })).toHaveAttribute(
      "href",
      "/projects/p/referrals?assessment=a1&category=liquor_licensing_consultant",
    );

    fireEvent.click(screen.getByRole("checkbox", { name: "Lodge the application" }));
    await waitFor(() =>
      expect(apiRequest).toHaveBeenCalledWith(
        "PATCH",
        "/organisations/org/projects/p/plan/steps/s1",
        { status: "DONE" },
      ),
    );
    expect(await screen.findByText("1 of 1 steps done (100%)")).toBeInTheDocument();
  });

  it("adds a follow-up call to a suggested partner", async () => {
    apiRequest.mockResolvedValue({
      ok: true,
      data: step({
        id: "f1",
        kind: "FOLLOW_UP",
        title: "Call Reef Licensing",
        due_on: "2026-10-14",
        editable: true,
        link_url: null,
        link_label: null,
      }),
    });
    render(
      <ProjectPlan
        organisationId="org"
        projectId="p"
        assessmentId="a1"
        plan={plan()}
        documents={[]}
        canWrite
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Add a follow-up call" }));
    await waitFor(() =>
      expect(apiRequest).toHaveBeenCalledWith(
        "POST",
        "/organisations/org/projects/p/plan/follow-ups",
        {
          partner_id: "p1",
          section_key: "approval:LIQUOR_LICENCE",
        },
      ),
    );
    expect(
      await screen.findByRole("checkbox", { name: "Call Reef Licensing" }),
    ).toBeInTheDocument();
  });
});

describe("PlanOffer", () => {
  beforeEach(() => apiRequest.mockReset());

  it("starts a free plan straight away while it isn't on sale", async () => {
    apiRequest.mockResolvedValue({ ok: true, data: { plan: plan(), checkout_url: null } });
    render(
      <PlanOffer
        organisationId="org"
        projectId="p"
        plan={{ status: "NONE", offer: OFFER, complimentary: false, sections: [] }}
        hasAssessment
        canWrite
        paymentReturn={null}
      />,
    );
    expect(screen.getByText("Free while we launch.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Start my project plan" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(apiRequest).toHaveBeenCalledWith("POST", "/organisations/org/projects/p/plan");
  });

  it("shows the price when it is on sale and asks for an assessment first", () => {
    render(
      <PlanOffer
        organisationId="org"
        projectId="p"
        plan={{
          status: "NONE",
          offer: { ...OFFER, on_sale: true, price_cents: 14900, currency: "AUD" },
          complimentary: false,
          sections: [],
        }}
        hasAssessment={false}
        canWrite
        paymentReturn={null}
      />,
    );
    expect(screen.getByText("$149.00")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Buy the project plan" })).toBeNull();
    expect(screen.getByRole("link", { name: /run it first/ })).toBeInTheDocument();
  });

  it("points to ApprovalReady Plus, and says when the membership includes the plan", () => {
    const { rerender } = render(
      <PlanOffer
        organisationId="org"
        projectId="p"
        plan={{
          status: "NONE",
          offer: { ...OFFER, on_sale: true, price_cents: 14900, membership_on_sale: true },
          complimentary: false,
          sections: [],
        }}
        hasAssessment
        canWrite
        paymentReturn={null}
      />,
    );
    expect(screen.getByRole("link", { name: "ApprovalReady Plus" })).toHaveAttribute(
      "href",
      "/membership",
    );
    rerender(
      <PlanOffer
        organisationId="org"
        projectId="p"
        plan={{
          status: "NONE",
          offer: { ...OFFER, included_in_membership: true },
          complimentary: false,
          sections: [],
        }}
        hasAssessment
        canWrite
        paymentReturn={null}
      />,
    );
    expect(screen.getByText(/Included in your ApprovalReady Plus membership/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "ApprovalReady Plus" })).toBeNull();
    expect(screen.getByRole("button", { name: "Start my project plan" })).toBeInTheDocument();
  });
});
