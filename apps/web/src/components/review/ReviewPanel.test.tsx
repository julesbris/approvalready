import type { ReviewOut } from "@approvalready/shared-types";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ReviewPanel } from "./ReviewPanel";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), refresh }) }));

const REVIEW: ReviewOut = {
  id: "r1",
  project_id: "p1",
  project_reference: "PLN-7K2M9Q",
  project_title: "Granny flat",
  vertical: "PLANNING",
  assessment_id: "a1",
  status: "CHANGES_REQUIRED",
  message: null,
  professional: {
    id: "pro1",
    display_name: "Pat Planner",
    discipline: "TOWN_PLANNER",
    practice_name: "Coastal Planning",
  },
  assigned_at: "2026-10-09T00:00:00Z",
  due_on: null,
  started_at: "2026-10-09T00:00:00Z",
  closed_at: null,
  created_at: "2026-10-09T00:00:00Z",
  cancel_refund_cents: 0,
  comments: [],
  overrides: [],
  decisions: [
    {
      id: "d1",
      assessment_id: "a1",
      decision: "CHANGES_REQUIRED",
      notes: "Add the site plan.",
      created_at: "2026-10-09T00:00:00Z",
    },
  ],
} as ReviewOut;

const props = {
  organisationId: "o1",
  projectId: "p1",
  assessmentId: "a1",
  isLatest: true,
  openElsewhere: null,
  canWrite: true,
};

afterEach(() => vi.unstubAllGlobals());

describe("ReviewPanel", () => {
  it("offers a review request on the latest assessment", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        Response.json({ ...REVIEW, status: "REVIEW_REQUESTED", professional: null, decisions: [] }),
      );
    vi.stubGlobal("fetch", fetchMock);
    render(<ReviewPanel {...props} review={null} />);
    fireEvent.change(screen.getByLabelText(/anything you'd like/i), {
      target: { value: "Is the setback right?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Request a professional review" }));
    await screen.findByText(/finding a reviewer/i);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/organisations/o1/projects/p1/reviews");
    expect(JSON.parse(init.body as string)).toEqual({
      assessment_id: "a1",
      message: "Is the setback right?",
    });
    expect(refresh).toHaveBeenCalled();
  });

  it("hides the request form from read-only members and older assessments", () => {
    const { container, rerender } = render(
      <ReviewPanel {...props} canWrite={false} review={null} />,
    );
    expect(container).toBeEmptyDOMElement();
    rerender(<ReviewPanel {...props} isLatest={false} review={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the reviewer's request for changes and sends the assessment back", async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ ...REVIEW, status: "IN_REVIEW" }));
    vi.stubGlobal("fetch", fetchMock);
    render(<ReviewPanel {...props} review={REVIEW} />);
    expect(screen.getByText(/Pat Planner, Town planner \(Coastal Planning\)/)).toBeInTheDocument();
    expect(screen.getByText(/Add the site plan/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Send back to your reviewer" }));
    await waitFor(() => expect(screen.getByText("Being reviewed")).toBeInTheDocument());
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/organisations/o1/reviews/r1/resubmit");
    expect(JSON.parse(init.body as string)).toEqual({ assessment_id: "a1" });
  });

  it("points to the review of another assessment", () => {
    render(
      <ReviewPanel
        {...props}
        review={null}
        openElsewhere={{ ...REVIEW, assessment_id: "a0" } as unknown as ReviewOut}
      />,
    );
    expect(screen.getByRole("link", { name: /another assessment/ })).toHaveAttribute(
      "href",
      "/projects/p1/assessments/a0",
    );
    expect(
      screen.getByRole("button", { name: "Send this assessment to your reviewer" }),
    ).toBeInTheDocument();
  });

  it("shows the price and sends the customer to Stripe to pay", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    const pending = {
      ...REVIEW,
      status: "PAYMENT_PENDING",
      professional: null,
      decisions: [],
      payment: {
        id: "pay1",
        status: "PENDING",
        amount_cents: 24_900,
        currency: "AUD",
        paid_at: null,
        refunded_cents: 0,
        refunds: [],
      },
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(Response.json(pending))
      .mockResolvedValueOnce(Response.json({ url: "https://checkout.stripe.com/c/pay/cs_1" }));
    vi.stubGlobal("fetch", fetchMock);
    const price = {
      id: "price1",
      amount_cents: 24_900,
      currency: "AUD",
      interval: "ONE_TIME" as const,
      active: true,
      created_at: "2026-10-10T00:00:00Z",
    };
    render(<ReviewPanel {...props} review={null} price={price} />);
    expect(screen.getByText("$249.00")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Request and pay" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://checkout.stripe.com/c/pay/cs_1"));
    const [checkoutUrl] = fetchMock.mock.calls[1] as [string];
    expect(checkoutUrl).toBe("/api/v1/organisations/o1/reviews/r1/checkout");
  });

  it("waits for a payment Stripe hasn't confirmed yet", () => {
    const pending = {
      ...REVIEW,
      status: "PAYMENT_PENDING",
      professional: null,
      decisions: [],
      payment: {
        id: "pay1",
        status: "PENDING",
        amount_cents: 9_900,
        currency: "AUD",
        paid_at: null,
        refunded_cents: 0,
        refunds: [],
      },
    } as ReviewOut;
    render(<ReviewPanel {...props} review={pending} paymentReturn="done" />);
    expect(screen.getByText(/confirming your payment/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pay $99.00" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel the request" })).toBeInTheDocument();
  });

  it("shows the refund on a cancelled review", () => {
    const cancelled = {
      ...REVIEW,
      status: "CANCELLED",
      payment: {
        id: "pay1",
        status: "REFUNDED",
        amount_cents: 24_900,
        currency: "AUD",
        paid_at: "2026-10-09T00:00:00Z",
        refunded_cents: 24_900,
        refunds: [
          {
            id: "re1",
            amount_cents: 24_900,
            currency: "AUD",
            reason: "REVIEW_CANCELLED",
            status: "SUCCEEDED",
            created_at: "2026-10-10T00:00:00Z",
            sent_at: "2026-10-10T00:00:00Z",
          },
        ],
      },
    } as ReviewOut;
    render(<ReviewPanel {...props} review={cancelled} />);
    expect(screen.getByText(/Refunded \$249\.00/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel the review" })).not.toBeInTheDocument();
  });
});
