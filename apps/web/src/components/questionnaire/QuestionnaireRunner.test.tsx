import type { CouncilOut, SubmissionOut } from "@approvalready/shared-types";
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

  it("offers answers from the site and saves the ones accepted", async () => {
    const saved = submission({
      answers: { kind: "sub" },
      missing_required: ["lots"],
      progress: { answered: 1, visible: 2, required_remaining: 1 },
    });
    const fetchMock = vi.fn().mockResolvedValue(Response.json(saved));
    vi.stubGlobal("fetch", fetchMock);
    render(
      <QuestionnaireRunner
        organisationId="o1"
        projectId="p1"
        submission={submission()}
        canWrite
        suggestions={[
          {
            key: "kind",
            label: "What are you planning?",
            value: "sub",
            source: "Mock provider",
            source_url: null,
            is_mock: true,
          },
        ]}
      />,
    );
    const panel = screen.getByRole("region", { name: "We can fill in an answer for you" });
    expect(panel).toHaveTextContent("Subdividing");
    expect(panel).toHaveTextContent("(test data, not real)");
    fireEvent.click(screen.getByRole("button", { name: "Use these answers" }));
    expect(await screen.findByText(/Filled in from your site details/)).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /We can fill in/ })).not.toBeInTheDocument();
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({ answers: { kind: "sub" } });
  });

  it("saves answers automatically a moment after they change", async () => {
    const saved = submission({
      answers: { kind: "ext" },
      missing_required: [],
      progress: { answered: 1, visible: 1, required_remaining: 0 },
    });
    const fetchMock = vi.fn().mockResolvedValue(Response.json(saved));
    vi.stubGlobal("fetch", fetchMock);
    render(
      <QuestionnaireRunner
        organisationId="o1"
        projectId="p1"
        submission={submission()}
        canWrite
        autosaveDelayMs={5}
      />,
    );
    expect(screen.getByText("Your answers save as you go.")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Extending"));
    expect(await screen.findByText(/All changes saved/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/organisations/o1/submissions/s1/answers");
    expect(JSON.parse(init.body as string)).toEqual({ answers: { kind: "ext" } });
    // Still on the same section: saving in the background doesn't move people on.
    expect(screen.getByLabelText("Extending")).toBeChecked();
  });

  it("fills in the council and lot from a picked address and shows how to apply", async () => {
    const site = submission({
      visible: ["property.address", "property.lga", "property.lot_plan"],
      missing_required: [],
      progress: { answered: 0, visible: 3, required_remaining: 0 },
      questionnaire: {
        ...submission().questionnaire,
        sections: [
          {
            title: "The site",
            questions: [
              {
                key: "property.address",
                type: "ADDRESS",
                label: "Site address",
                help_text: null,
                required: false,
                options: [],
                validation: {},
                visible_when: null,
              },
              {
                key: "property.lga",
                type: "SELECT",
                label: "Which council area is the site in?",
                help_text: null,
                required: false,
                options: [
                  { value: "brisbane", label: "Brisbane City Council" },
                  { value: "cairns", label: "Cairns Regional Council" },
                  { value: "other", label: "A council outside Queensland" },
                ],
                validation: {},
                visible_when: null,
              },
              {
                key: "property.lot_plan",
                type: "TEXT",
                label: "Lot and plan",
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
    });
    const council = {
      key: "cairns",
      name: "Cairns Regional Council",
      checked_on: "2026-10-11",
      checked: { verified: false, verified_at: null },
      lodgement: [],
      steps: ["Lodge online."],
      general_steps: ["Check the planning scheme."],
      general_source: { url: "https://planning.example/process", title: "Process" },
      contact: { phone: "07 4044 3044", email: null, address: null, hours: null },
      fees: null,
      sources: [{ url: "https://cairns.example/da", title: "Development applications" }],
      gaps: [],
    } as unknown as CouncilOut;
    const fetchMock = vi.fn((url: string) => {
      if (url.includes("/lookups/addresses")) {
        return Promise.resolve(
          Response.json({
            matches: [
              {
                address_pid: 1,
                label: "34 Gilmore Street, Bentley Park QLD",
                line1: "34 Gilmore Street",
                suburb: "Bentley Park",
                state: "QLD",
                lot_plan: "1RP731159",
                lot_plan_label: "Lot 1 on RP731159",
                local_authority: "Cairns Regional",
                lga: "cairns",
              },
            ],
            note: "",
            source: "",
          }),
        );
      }
      if (url.includes("/councils/cairns")) return Promise.resolve(Response.json(council));
      if (url.includes("/prefill")) {
        return Promise.resolve(Response.json({ provider: "none", suggestions: [] }));
      }
      return Promise.resolve(Response.json(site));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <QuestionnaireRunner
        organisationId="o1"
        projectId="p1"
        submission={site}
        canWrite
        autosaveDelayMs={5}
      />,
    );
    fireEvent.change(screen.getByLabelText("Find a Queensland address"), {
      target: { value: "34 Gilmore St" },
    });
    fireEvent.click(await screen.findByRole("button", { name: /34 Gilmore Street/ }));
    expect(screen.getByLabelText("Cairns Regional Council")).toBeChecked();
    expect(screen.getByLabelText(/Lot and plan/)).toHaveValue("Lot 1 on RP731159");
    expect(screen.getByText(/We filled in the council and lot and plan/)).toBeInTheDocument();
    expect(
      await screen.findByText(/Development applications for this site go to Cairns Regional/),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/answers"))).toBe(true),
    );
    const save = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/answers")) as unknown as [
      string,
      RequestInit,
    ];
    expect(JSON.parse(save[1].body as string).answers).toMatchObject({
      "property.lga": "cairns",
      "property.lot_plan": "Lot 1 on RP731159",
    });
  });
});
