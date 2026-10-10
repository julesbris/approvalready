import type { AIJobOut, GrantMatchOut } from "@approvalready/shared-types";
import { fireEvent, render, screen, within } from "@testing-library/react";

import { formatMicros } from "@/components/admin/AIUsage";
import { currentJob } from "@/lib/ai";

import { AIExplanation } from "./AIExplanation";
import { GrantDrafts } from "./GrantDrafts";

const BASE: AIJobOut = {
  id: "j1",
  task: "ASSESSMENT_EXPLANATION",
  status: "SUCCEEDED",
  assessment_id: "a1",
  subject_id: null,
  prompt_version: 1,
  output_schema: "assessment_explanation.v1",
  explanation: {
    summary: "Your granny flat needs a development application.",
    points: [{ text: "Over 80 m2 needs approval.", finding_ids: ["f1"] }],
    next_steps: [],
    open_questions: [{ text: "How big is the lot?", finding_ids: ["f2"] }],
  },
  grant_draft: null,
  error: null,
  validation_errors: [],
  created_at: "2026-10-10T00:00:00Z",
  completed_at: "2026-10-10T00:00:05Z",
};

const TITLES = { f1: "Floor area", f2: "Lot size" };

describe("currentJob", () => {
  it("prefers a pending job, then the newest that worked", () => {
    const failed = { ...BASE, id: "j2", status: "REJECTED", created_at: "2026-10-11T00:00:00Z" };
    expect(currentJob([BASE, failed] as AIJobOut[], "ASSESSMENT_EXPLANATION")?.id).toBe("j1");
    const pending = { ...failed, id: "j3", status: "PENDING" };
    expect(currentJob([BASE, pending] as AIJobOut[], "ASSESSMENT_EXPLANATION")?.id).toBe("j3");
    expect(currentJob([BASE], "GRANT_DRAFT")).toBeUndefined();
  });
});

describe("AIExplanation", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("marks the text as an AI draft and links each point to its findings", () => {
    render(
      <AIExplanation organisationId="o1" assessmentId="a1" jobs={[BASE]} findingTitles={TITLES} canWrite />,
    );
    expect(screen.getByText("AI draft")).toBeInTheDocument();
    expect(screen.getByText(/It only rewords them/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Floor area" })).toHaveAttribute("href", "#finding-f1");
    expect(screen.getByRole("link", { name: "Lot size" })).toHaveAttribute("href", "#finding-f2");
    expect(screen.getByRole("button", { name: "Write it again" })).toBeInTheDocument();
  });

  it("asks for an explanation and waits for it", async () => {
    const pending = { ...BASE, status: "PENDING", explanation: null };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(Response.json(pending, { status: 202 }))
      .mockResolvedValueOnce(Response.json(BASE));
    vi.stubGlobal("fetch", fetchMock);
    render(
      <AIExplanation
        organisationId="o1"
        assessmentId="a1"
        jobs={[]}
        findingTitles={TITLES}
        canWrite
        pollMs={1}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Explain these findings in plain language" }));
    expect(await screen.findByText(BASE.explanation!.summary)).toBeInTheDocument();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/organisations/o1/assessments/a1/ai/explanation");
    expect(JSON.parse(init.body as string)).toEqual({ regenerate: false });
  });

  it("shows why a rejected draft isn't shown, and no text from it", () => {
    const rejected = {
      ...BASE,
      status: "REJECTED",
      explanation: null,
      error: "The AI draft did not pass our checks, so it is not shown. Try again.",
    } as AIJobOut;
    render(
      <AIExplanation organisationId="o1" assessmentId="a1" jobs={[rejected]} findingTitles={TITLES} canWrite={false} />,
    );
    expect(screen.getByText(/did not pass our checks/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

const MATCH = {
  id: "m1",
  status: "STRONG_MATCH",
  confidence: "LIKELY",
  criteria: [{ kind: "CRITERION", finding_id: "f9", title: "Fewer than 20 staff", result: "MATCH" }],
  missing_facts: [],
  round_id_at_assessment: null,
  program: { id: "p1", title: "Growth Grant" },
} as unknown as GrantMatchOut;

describe("GrantDrafts", () => {
  it("shows notes per eligible program with what each section is based on", () => {
    const job = {
      ...BASE,
      task: "GRANT_DRAFT",
      subject_id: "p1",
      explanation: null,
      grant_draft: {
        sections: [
          {
            heading: "About the business",
            text: "A small manufacturer.",
            finding_ids: ["f9"],
            fact_keys: ["grant.employee_band"],
          },
        ],
        missing_information: ["Quotes for the machine"],
      },
    } as AIJobOut;
    const ineligible = { ...MATCH, status: "NOT_ELIGIBLE", program: { id: "p2", title: "Export Grant" } };
    render(
      <GrantDrafts
        organisationId="o1"
        assessmentId="a1"
        matches={[MATCH, ineligible as GrantMatchOut]}
        jobs={[job]}
        labels={{ "grant.employee_band": "Number of employees" }}
        canWrite
      />,
    );
    const panel = screen.getByRole("region", { name: /Application notes/ });
    expect(within(panel).getByText("A small manufacturer.")).toBeInTheDocument();
    expect(
      within(panel).getByText("Based on: Fewer than 20 staff; Number of employees"),
    ).toBeInTheDocument();
    expect(within(panel).getByText("Quotes for the machine")).toBeInTheDocument();
    expect(within(panel).queryByText("Export Grant")).not.toBeInTheDocument();
    expect(within(panel).getByText(/say nothing about your chances/)).toBeInTheDocument();
  });

  it("renders nothing when no program can be drafted for", () => {
    const { container } = render(
      <GrantDrafts
        organisationId="o1"
        assessmentId="a1"
        matches={[{ ...MATCH, status: "NOT_ELIGIBLE" } as GrantMatchOut]}
        jobs={[]}
        labels={{}}
        canWrite
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe("formatMicros", () => {
  it("shows dollars to the cent", () => {
    expect(formatMicros(14_000)).toBe("$0.01");
    expect(formatMicros(2_500_000)).toBe("$2.50");
    expect(formatMicros(500)).toBe("< $0.01");
    expect(formatMicros(0)).toBe("$0.00");
  });
});
