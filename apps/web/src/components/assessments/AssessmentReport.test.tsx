import type { AssessmentOut, FindingOut } from "@approvalready/shared-types";
import { render, screen, within } from "@testing-library/react";

import { AssessmentReport } from "./AssessmentReport";

const SOURCE = {
  reference_id: "r1",
  citation: "Test Planning Scheme, s. 6.2",
  url: "https://example.com/scheme",
  organisation_name: "Test Council",
  document_title: "Test Planning Scheme",
  section: "6.2",
  clause: null,
  page: null,
  relationship: "BASIS",
  verification_status: "VERIFIED",
  in_force: true,
} as FindingOut["sources"][number];

const FINDING: FindingOut = {
  id: "f1",
  rule_set_id: "rs1",
  rule_version_id: "v1",
  rule_key: "floor-area",
  rule_title: "Floor area limit",
  result: "MATCH",
  outcome_type: "APPROVAL_REQUIRED",
  title: "Development approval needed",
  detail: "Larger secondary dwellings need approval.",
  confidence: "VERIFIED",
  confidence_reasons: [],
  missing_facts: [],
  trace: {
    kind: "leaf",
    fact: "planning.floor_area_m2",
    op: "greater_than",
    value: 80,
    actual: { $decimal: "92.5" },
    missing: false,
    result: "TRUE",
  },
  sources: [SOURCE],
  referral_categories: ["town_planner"],
};

const ASSESSMENT: AssessmentOut = {
  id: "a1234567-0000-0000-0000-000000000000",
  project_id: "p1",
  submission_id: "s1",
  assessed_on: "2026-10-08",
  created_at: "2026-10-08T01:00:00Z",
  engine_version: "rules-engine/1",
  facts: {},
  facts_hash: "abcdef0123456789",
  fact_labels: {
    "planning.floor_area_m2": "Floor area (m²)",
    "planning.lot_size_m2": "Lot size (m²)",
  },
  status: "COMPLETED",
  overall_confidence: "UNKNOWN",
  findings: 2,
  rule_sets: [],
  approval_requirements: [],
  evidence_requirements: [],
  referral_categories: [],
  limitations: [],
  finding_list: [
    FINDING,
    {
      ...FINDING,
      id: "f2",
      rule_title: "Lot size",
      result: "UNKNOWN",
      outcome_type: "PROFESSIONAL_REQUIRED",
      title: "We need your lot size",
      detail: null,
      confidence: "UNKNOWN",
      missing_facts: ["planning.lot_size_m2"],
    },
  ],
};

describe("AssessmentReport", () => {
  it("explains each finding with the customer's answers and its sources", () => {
    render(<AssessmentReport assessment={ASSESSMENT} projectId="p1" />);
    expect(screen.getByText(/not legal or professional advice/)).toBeInTheDocument();

    const act = screen.getByRole("region", { name: "What you may need to do" });
    expect(within(act).getByText("Development approval needed")).toBeInTheDocument();
    expect(within(act).getByText("Verified")).toBeInTheDocument();
    expect(
      within(act).getByText("Floor area (m²): 92.5 (checked: is more than 80)"),
    ).toBeInTheDocument();
    expect(within(act).getByRole("link", { name: "Test Planning Scheme, s. 6.2" })).toHaveAttribute(
      "href",
      "https://example.com/scheme",
    );

    const missing = screen.getByRole("region", {
      name: "What we need to know",
    });
    expect(within(missing).getByText("Lot size (m²)")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Update your answers" })).toHaveAttribute(
      "href",
      "/projects/p1/questionnaire",
    );
  });

  it("lists approvals, evidence, who can help, sources and limitations", () => {
    render(
      <AssessmentReport
        assessment={{
          ...ASSESSMENT,
          approval_requirements: [
            {
              id: "ar1",
              finding_id: "f1",
              kind: "PLANNING_MATERIAL_CHANGE_OF_USE",
              title: "Development approval needed",
              authority: "Test Council",
              pathway: "Code assessment",
              certainty: "LIKELY_REQUIRED",
              confidence: "LIKELY",
            },
          ],
          evidence_requirements: [
            {
              id: "er1",
              finding_id: "f1",
              kind: "SITE_PLAN",
              title: "Site plan showing parking",
              detail: null,
              confidence: "LIKELY",
            },
          ],
          referral_categories: [
            { key: "town_planner", finding_ids: ["f1"] },
            { key: "drainage_engineer", finding_ids: ["f1"] },
          ],
          limitations: ["Does not check overlays."],
        }}
        projectId="p1"
      />,
    );
    const approvals = screen.getByRole("region", { name: "Approvals and what you'll need" });
    expect(within(approvals).getByText("Likely required · Test Council")).toBeInTheDocument();
    expect(within(approvals).getByText("Code assessment")).toBeInTheDocument();
    expect(within(approvals).getByText("Site plan showing parking")).toBeInTheDocument();

    const help = screen.getByRole("region", { name: "Who can help" });
    expect(within(help).getByText("Town planner")).toBeInTheDocument();
    expect(within(help).getByText("Drainage engineer")).toBeInTheDocument();

    const sources = screen.getByRole("region", { name: "Sources" });
    expect(within(sources).getAllByRole("link")).toHaveLength(1);
    expect(within(sources).getByText("Test Council · Verified")).toBeInTheDocument();

    const limits = screen.getByRole("region", { name: "What this assessment doesn't check" });
    expect(within(limits).getByText("Does not check overlays.")).toBeInTheDocument();
  });

  it("never implies no approval is needed when no rules apply", () => {
    render(
      <AssessmentReport
        assessment={{
          ...ASSESSMENT,
          status: "NO_APPLICABLE_RULES",
          finding_list: [],
        }}
        projectId="p1"
      />,
    );
    expect(screen.getByText(/This does not mean none is needed/)).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "What you may need to do" })).toBeNull();
  });
});
