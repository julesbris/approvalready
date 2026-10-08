import type {
  PublishChecksOut,
  RuleOut,
  RuleVersionOut,
  SourceReferenceOut,
} from "@approvalready/shared-types";
import { fireEvent, render, screen } from "@testing-library/react";

import { RuleVersionEditor } from "./RuleVersionEditor";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

const VERSION: RuleVersionOut = {
  id: "v1",
  rule_id: "r1",
  rule_key: "floor-area",
  rule_title: "Floor area limit",
  rule_set_id: "rs1",
  rule_set_key: "test-planning",
  vertical: "PLANNING",
  version: 1,
  status: "DRAFT",
  condition: { fact: "planning.floor_area_m2", op: "greater_than", value: 80 },
  fact_paths: ["planning.floor_area_m2"],
  effective_from: "2026-01-01",
  effective_to: null,
  max_confidence: "VERIFIED",
  notes: null,
  outcomes: [
    {
      on_result: "MATCH",
      outcome_type: "APPROVAL_REQUIRED",
      title: "Approval needed",
      detail: null,
    },
  ],
  sources: [],
  test_cases: [],
  content_hash: null,
  created_at: "2026-10-08T00:00:00Z",
  created_by: null,
  updated_at: "2026-10-08T00:00:00Z",
  published_at: null,
  published_by: null,
};

const RULE: RuleOut = {
  id: "r1",
  rule_set_id: "rs1",
  rule_set_key: "test-planning",
  key: "floor-area",
  title: "Floor area limit",
  versions: [
    {
      id: "v1",
      version: 1,
      status: "DRAFT",
      effective_from: "2026-01-01",
      effective_to: null,
      published_at: null,
      created_at: "2026-10-08T00:00:00Z",
    },
  ],
};

const CHECKS: PublishChecksOut = {
  ready: false,
  checks: [
    { key: "condition", passed: true, message: "The condition is valid." },
    {
      key: "basis_source",
      passed: false,
      message: "Link at least one basis source.",
    },
  ],
  warnings: [],
  test_results: [],
};

const REFERENCE = {
  id: "ref1",
  citation: "Test Planning Scheme, s. 6.2",
  verification_status: "VERIFIED",
} as SourceReferenceOut;

function renderEditor(version = VERSION, canPublish = true) {
  return render(
    <RuleVersionEditor
      version={version}
      rule={RULE}
      checks={CHECKS}
      references={[REFERENCE]}
      canPublish={canPublish}
    />,
  );
}

describe("RuleVersionEditor", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows the publish gate and blocks publishing until it passes", () => {
    renderEditor();
    expect(screen.getByText("Link at least one basis source.")).toHaveClass("check-fail");
    expect(screen.getByRole("button", { name: "Publish v1" })).toBeDisabled();
  });

  it("saves the draft with linked sources and outcomes", async () => {
    const fetchMock = vi.fn(async () => Response.json(VERSION));
    vi.stubGlobal("fetch", fetchMock);
    renderEditor();
    fireEvent.change(screen.getByLabelText("Add a source"), {
      target: { value: "ref1" },
    });
    expect(screen.getByText(/Test Planning Scheme, s. 6.2/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/v1/admin/rule-versions/v1");
    const body = JSON.parse(String(init.body)) as Record<string, unknown>;
    expect(body.sources).toEqual([{ source_reference_id: "ref1", relationship: "BASIS" }]);
    expect(body.outcomes).toEqual([
      {
        on_result: "MATCH",
        outcome_type: "APPROVAL_REQUIRED",
        title: "Approval needed",
        detail: null,
      },
    ]);
  });

  it("rejects invalid condition JSON before calling the API", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    renderEditor();
    fireEvent.change(screen.getByLabelText(/Condition \(JSON\)/), {
      target: { value: "{" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(screen.getByText("The condition is not valid JSON.")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("is read-only once published", () => {
    renderEditor({ ...VERSION, status: "PUBLISHED" });
    expect(screen.queryByRole("button", { name: "Save draft" })).toBeNull();
    expect(screen.getByLabelText(/Condition \(JSON\)/)).toBeDisabled();
    expect(screen.getByRole("button", { name: "Retire" })).toBeInTheDocument();
  });
});
