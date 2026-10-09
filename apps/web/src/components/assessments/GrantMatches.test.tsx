import type {
  GrantMatchOut,
  GrantProgramOut,
} from "@approvalready/shared-types";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { GrantMatches } from "./GrantMatches";

const PROGRAM: GrantProgramOut = {
  id: "p1",
  key: "test.grant",
  title: "Test Growth Grant",
  summary: "A fictional grant for tests.",
  administrator: { id: "o1", name: "Test Grant Body" },
  jurisdiction: "QLD",
  url: "https://example.com/grant",
  rule_set_id: "rs1",
  rule_set_key: "test.grant",
  funding_summary: "You fund at least half.",
  min_amount_cents: 5_000_000,
  max_amount_cents: 7_500_000,
  status: "ACTIVE",
  current_round_id: "r1",
  rounds: [
    {
      id: "r1",
      program_id: "p1",
      title: "Round 7",
      status: "OPEN",
      state: "OPEN",
      opens_on: null,
      closes_on: "2026-10-16",
      dates_note: "5pm AEST",
      days_to_close: 7,
      closing_soon: true,
      check_source: false,
      source: {
        reference_id: "ref1",
        citation: "Grant guidelines, Key dates",
        url: "https://example.com/guidelines",
        verification_status: "UNVERIFIED",
      },
      updated_at: "2026-10-09T00:00:00Z",
    },
  ],
};

function match(overrides: Partial<GrantMatchOut>): GrantMatchOut {
  return {
    id: "m1",
    status: "STRONG_MATCH",
    confidence: "LIKELY",
    criteria: [
      {
        kind: "CRITERION",
        finding_id: "f1",
        title: "Fewer than 20 employees",
        result: "MATCH",
        outcome: null,
        missing_facts: [],
      },
    ],
    missing_facts: [],
    round_id_at_assessment: "r1",
    program: PROGRAM,
    ...overrides,
  };
}

describe("GrantMatches", () => {
  it("groups programs by match and shows the round and its source", () => {
    render(
      <GrantMatches
        labels={{ "grant.employee_band": "Number of employees" }}
        matches={[
          match({}),
          match({
            id: "m2",
            status: "NEEDS_INFORMATION",
            confidence: "UNKNOWN",
            missing_facts: ["grant.employee_band"],
            criteria: [
              {
                kind: "CRITERION",
                finding_id: "f2",
                title: "Fewer than 20 employees",
                result: "UNKNOWN",
                outcome: null,
                missing_facts: ["grant.employee_band"],
              },
            ],
            program: {
              ...PROGRAM,
              id: "p2",
              title: "Other Grant",
              rounds: [],
              current_round_id: null,
            },
          }),
        ]}
      />,
    );
    const strong = screen.getByRole("heading", {
      name: /Programs you meet the criteria for/,
    });
    expect(strong).toBeInTheDocument();
    const first = screen
      .getByRole("heading", { name: "Test Growth Grant" })
      .closest("li")!;
    expect(within(first).getByText("Open")).toBeInTheDocument();
    expect(within(first).getByText(/\$50,000 to \$75,000/)).toBeInTheDocument();
    expect(within(first).getByText("Met")).toBeInTheDocument();
    expect(
      within(first).getByRole("link", { name: "Grant guidelines, Key dates" }),
    ).toHaveAttribute("href", "https://example.com/guidelines");
    expect(
      within(first).getByText(/7 days left\)\. Check the program/),
    ).toBeInTheDocument();

    const second = screen
      .getByRole("heading", { name: "Other Grant" })
      .closest("li")!;
    expect(within(second).getByText("No round")).toBeInTheDocument();
    expect(
      within(second).getByText(/tell us: Number of employees/),
    ).toBeInTheDocument();
    expect(within(second).getByText("Not answered")).toBeInTheDocument();
    expect(
      screen.getByText(/We never estimate your chances/),
    ).toBeInTheDocument();
  });
});
