import type { SubmissionOut } from "@approvalready/shared-types";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { QuestionnaireRunner } from "./QuestionnaireRunner";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));

function submission(overrides: Partial<SubmissionOut> = {}): SubmissionOut {
  return {
    id: "s1",
    project_id: "p1",
    status: "IN_PROGRESS",
    submitted_at: null,
    updated_at: "2026-10-04T00:00:00Z",
    answers: {},
    visible: ["kind"],
    missing_required: ["kind"],
    pruned: [],
    progress: { answered: 0, visible: 1, required_remaining: 1 },
    questionnaire: {
      key: "t.general",
      vertical: "PLANNING",
      version: 3,
      title: "Tell us about it",
      description: null,
      sections: [
        {
          title: "Plans",
          questions: [
            {
              key: "kind",
              type: "SELECT",
              label: "What are you planning?",
              help_text: null,
              required: true,
              options: [
                { value: "sub", label: "Subdividing" },
                { value: "ext", label: "Extending" },
              ],
              validation: {},
              visible_when: null,
            },
            {
              key: "lots",
              type: "NUMBER",
              label: "How many lots?",
              help_text: null,
              required: true,
              options: [],
              validation: {},
              visible_when: { fact: "kind", op: "equals", value: "sub" },
            },
          ],
        },
        {
          title: "Costs",
          questions: [
            {
              key: "budget",
              type: "CURRENCY",
              label: "Budget",
              help_text: null,
              required: false,
              options: [],
              validation: {},
              visible_when: null,
            },
          ],
        },
      ],
    },
    ...overrides,
  };
}

function renderRunner(initial = submission()) {
  return render(
    <QuestionnaireRunner organisationId="o1" projectId="p1" submission={initial} canWrite />,
  );
}

describe("QuestionnaireRunner", () => {
  beforeEach(() => {
    window.scrollTo = vi.fn() as unknown as typeof window.scrollTo;
  });
  afterEach(() => vi.unstubAllGlobals());

  it("shows follow-up questions as soon as an answer makes them apply", () => {
    renderRunner();
    expect(screen.queryByLabelText("How many lots?")).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Subdividing"));
    expect(screen.getByLabelText("How many lots?")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Extending"));
    expect(screen.queryByLabelText("How many lots?")).not.toBeInTheDocument();
  });

  it("saves the section's visible answers and moves on", async () => {
    const saved = submission({
      answers: { kind: "sub", lots: 3 },
      visible: ["kind", "lots", "budget"],
      missing_required: [],
      progress: { answered: 2, visible: 3, required_remaining: 0 },
    });
    const fetchMock = vi.fn().mockResolvedValue(Response.json(saved));
    vi.stubGlobal("fetch", fetchMock);
    renderRunner();
    fireEvent.click(screen.getByLabelText("Subdividing"));
    fireEvent.change(screen.getByLabelText("How many lots?"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "Save and continue" }));
    expect(await screen.findByLabelText(/Budget/)).toBeInTheDocument();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/organisations/o1/submissions/s1/answers");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual({ answers: { kind: "sub", lots: 3 } });
  });

  it("doesn't send half-typed numbers", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    renderRunner();
    fireEvent.click(screen.getByLabelText("Subdividing"));
    fireEvent.change(screen.getByLabelText("How many lots?"), { target: { value: "3.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Save and continue" }));
    expect(screen.getByText("Enter a whole number.")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows the API's message against each question", async () => {
    const body = {
      detail: { code: "invalid_answers", message: "Check.", fields: { lots: "Enter 2 or more." } },
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(body, { status: 422 })));
    renderRunner();
    fireEvent.click(screen.getByLabelText("Subdividing"));
    fireEvent.change(screen.getByLabelText("How many lots?"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Save and continue" }));
    expect(await screen.findByText("Enter 2 or more.")).toBeInTheDocument();
    expect(screen.getByLabelText("How many lots?")).toHaveAttribute("aria-invalid", "true");
  });

  it("won't submit while required answers are missing", async () => {
    renderRunner();
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    expect(screen.getByText("Required: not answered yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Submit answers" })).toBeDisabled();
  });

  it("opens submitted answers on the review and can reopen them", async () => {
    const reopened = submission({ answers: { kind: "ext" }, missing_required: [] });
    const fetchMock = vi.fn().mockResolvedValue(Response.json(reopened));
    vi.stubGlobal("fetch", fetchMock);
    renderRunner(
      submission({
        status: "SUBMITTED",
        submitted_at: "2026-10-04T00:00:00Z",
        answers: { kind: "ext" },
        missing_required: [],
      }),
    );
    expect(screen.getByText("Extending")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Submit answers" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Change answers" }));
    await waitFor(() => expect(screen.getByLabelText("Extending")).toBeChecked());
    expect((fetchMock.mock.calls[0] as [string])[0]).toBe("/api/v1/organisations/o1/submissions/s1/reopen");
  });
});
