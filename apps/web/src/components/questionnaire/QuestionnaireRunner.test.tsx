import type { AssessmentOut, CouncilOut, SubmissionOut } from "@approvalready/shared-types";
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

const ASSESSMENT: AssessmentOut = {
  id: "a1",
  project_id: "p1",
  submission_id: "s1",
  assessed_on: "2026-10-11",
  created_at: "2026-10-11T01:00:00Z",
  engine_version: "rules-engine/1",
  facts: {},
  facts_hash: "abcdef0123456789",
  fact_labels: {},
  status: "COMPLETED",
  overall_confidence: "LIKELY",
  findings: 0,
  rule_sets: [],
  approval_requirements: [
    {
      id: "r1",
      kind: "development_permit",
      title: "Development permit",
      authority: "Cairns Regional Council",
      certainty: "REQUIRED",
      confidence: "LIKELY",
      pathway: "Code assessment",
    },
  ] as AssessmentOut["approval_requirements"],
  approval_map: [],
  evidence_requirements: [],
  referral_categories: [],
  limitations: [],
  finding_list: [],
};

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
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByText("Enter 2 or more.")).toBeInTheDocument();
    expect(screen.getByLabelText("How many lots?")).toHaveAttribute("aria-invalid", "true");
  });

  it("shows the result right under the answers once the last section is done", async () => {
    const saved = submission({
      answers: { kind: "ext" },
      visible: ["kind", "budget"],
      missing_required: [],
      progress: { answered: 1, visible: 2, required_remaining: 0 },
    });
    const submitted = { ...saved, status: "SUBMITTED", submitted_at: "2026-10-11T01:00:00Z" };
    const fetchMock = vi.fn((url: string) =>
      Promise.resolve(
        url.endsWith("/result")
          ? Response.json({ submission: submitted, assessment: ASSESSMENT })
          : url.includes("/guidance/approvals")
            ? Response.json([])
            : Response.json(saved),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderRunner();
    expect(screen.getByText(/Step 1 of 2/)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Extending"));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByText(/Step 2 of 2/)).toBeInTheDocument();
    // The last section's one button submits and assesses in one go.
    fireEvent.click(screen.getByRole("button", { name: "See my result" }));
    expect(await screen.findByRole("heading", { name: "1 approval found" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Your result" })).toBeInTheDocument();
    expect(screen.getByText("Development permit")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open your full report" })).toHaveAttribute(
      "href",
      "/projects/p1/assessments/a1",
    );
    const urls = fetchMock.mock.calls.map(([url]) => String(url));
    expect(urls).toContain("/api/v1/organisations/o1/submissions/s1/result");
    expect(urls.some((url) => url.includes("/guidance/approvals?kind=development_permit"))).toBe(
      true,
    );
  });

  it("takes people back to what's still unanswered instead of showing a result", async () => {
    const body = {
      detail: {
        code: "answers_incomplete",
        message: "Answer the remaining required questions before submitting.",
        fields: { kind: "This question needs an answer." },
      },
    };
    const fetchMock = vi.fn((url: string) =>
      Promise.resolve(
        url.endsWith("/result")
          ? Response.json(body, { status: 422 })
          : Response.json(submission({ visible: ["kind", "budget"] })),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    // Submitted answers whose result was never worked out open on the result step.
    renderRunner(
      submission({ status: "SUBMITTED", submitted_at: "2026-10-04T00:00:00Z", missing_required: [] }),
    );
    fireEvent.click(screen.getByRole("button", { name: "See my result" }));
    expect(await screen.findByText("This question needs an answer.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Plans" })).toBeInTheDocument();
    expect(screen.getByText("Answer the highlighted questions to see your result.")).toBeInTheDocument();
  });

  it("opens submitted answers with their result, and reopens them to change one", async () => {
    const reopened = submission({ answers: { kind: "ext" }, missing_required: [] });
    const fetchMock = vi.fn(() => Promise.resolve(Response.json(reopened)));
    vi.stubGlobal("fetch", fetchMock);
    render(
      <QuestionnaireRunner
        organisationId="o1"
        projectId="p1"
        canWrite
        assessment={ASSESSMENT}
        submission={submission({
          status: "SUBMITTED",
          submitted_at: "2026-10-04T00:00:00Z",
          answers: { kind: "ext" },
          missing_required: [],
        })}
      />,
    );
    expect(screen.getByRole("heading", { name: "1 approval found" })).toBeInTheDocument();
    expect(screen.getByText("Extending")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "See my result" })).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Change" })[0]!);
    await waitFor(() => expect(screen.getByLabelText("Extending")).toBeChecked());
    expect((fetchMock.mock.calls[0] as unknown as [string])[0]).toBe("/api/v1/organisations/o1/submissions/s1/reopen");
    // Finishing again updates the result rather than starting over.
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("button", { name: "Update my result" })).toBeInTheDocument();
  });

  it("fills in answers from the site, saves them, and can undo them", async () => {
    const saved = submission({
      answers: { kind: "sub" },
      missing_required: ["lots"],
      progress: { answered: 1, visible: 2, required_remaining: 1 },
    });
    const fetchMock = vi.fn(() => Promise.resolve(Response.json(saved)));
    vi.stubGlobal("fetch", fetchMock);
    render(
      <QuestionnaireRunner
        organisationId="o1"
        projectId="p1"
        submission={submission()}
        canWrite
        autosaveDelayMs={5}
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
    const panel = screen.getByRole("region", { name: "We filled in an answer for you" });
    expect(panel).toHaveTextContent("Subdividing");
    expect(panel).toHaveTextContent("(test data, not real)");
    expect(screen.getByLabelText("Subdividing")).toBeChecked();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({ answers: { kind: "sub" } });

    fireEvent.click(screen.getByRole("button", { name: "Undo these" }));
    expect(screen.getByLabelText("Subdividing")).not.toBeChecked();
    expect(screen.queryByRole("region", { name: /We filled in/ })).not.toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const [, undo] = fetchMock.mock.calls[1] as unknown as [string, RequestInit];
    expect(JSON.parse(undo.body as string)).toEqual({ answers: { kind: null } });
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
    expect(screen.getByText("Saves as you go")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Extending"));
    expect(await screen.findByText("Saved")).toBeInTheDocument();
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
              {
                key: "property.land_area_m2",
                type: "DECIMAL",
                label: "Land area (square metres)",
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
      state: "QLD",
      state_fees: null,
      state_portal: null,
      planning_scheme_label: "planning scheme",
      zoning_lookup_url: null,
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
                postcode: "4869",
              },
            ],
            note: "",
            source: "",
          }),
        );
      }
      if (url.includes("/councils/cairns")) return Promise.resolve(Response.json(council));
      if (url.includes("/prefill")) {
        const from = (key: string, label: string, value: unknown) => ({
          key,
          label,
          value,
          source: "Queensland Government land parcel data",
          source_url: null,
          is_mock: false,
        });
        return Promise.resolve(
          Response.json({
            provider: "qld_spatial",
            suggestions: [
              from("property.lot_plan", "Lot and plan", "1RP731159"),
              from("property.land_area_m2", "Land area (square metres)", "774"),
            ],
          }),
        );
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
    fireEvent.change(screen.getByLabelText("Find the address"), {
      target: { value: "34 Gilmore St" },
    });
    fireEvent.click(await screen.findByRole("button", { name: /34 Gilmore Street/ }));
    expect(screen.getByLabelText("Cairns Regional Council")).toBeChecked();
    expect(screen.getByLabelText(/Lot and plan/)).toHaveValue("Lot 1 on RP731159");
    expect(screen.getByLabelText("Postcode")).toHaveValue("4869");
    expect(
      screen.getByText(/We filled in the postcode, council and lot and plan/),
    ).toBeInTheDocument();
    // Once the address saves, what else we can look up is filled in; the lot and plan just
    // picked is kept as it is.
    await waitFor(() =>
      expect(screen.getByLabelText(/^Land area/)).toHaveValue("774"),
    );
    expect(screen.getByLabelText(/Lot and plan/)).toHaveValue("Lot 1 on RP731159");
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
