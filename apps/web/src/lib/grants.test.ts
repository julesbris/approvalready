import type {
  GrantProgramOut,
  GrantRoundOut,
} from "@approvalready/shared-types";
import { describe, expect, it } from "vitest";

import { amountRange, currentRound, roundSummary } from "./grants";

const ROUND: GrantRoundOut = {
  id: "r1",
  program_id: "p1",
  title: "Round 2",
  status: "OPEN",
  state: "OPEN",
  opens_on: "2026-09-01",
  closes_on: "2026-10-21",
  dates_note: null,
  days_to_close: 12,
  closing_soon: true,
  check_source: false,
  source: {
    reference_id: "ref1",
    citation: "Grant guidelines, Key dates",
    url: "https://example.com/grant",
    verification_status: "UNVERIFIED",
  },
  updated_at: "2026-10-09T00:00:00Z",
};

describe("amountRange", () => {
  it("formats whole dollars", () => {
    expect(amountRange(2_000_000, 8_000_000)).toBe("$20,000 to $80,000");
    expect(amountRange(null, 7_500_000)).toBe("Up to $75,000");
    expect(amountRange(5_000_000, null)).toBe("From $50,000");
    expect(amountRange(5_000_000, 5_000_000)).toBe("$50,000");
    expect(amountRange(null, null)).toBeNull();
  });
});

describe("roundSummary", () => {
  it("says how long an open round has left", () => {
    expect(roundSummary(ROUND)).toBe("Open, closes 21 Oct 2026 (12 days left)");
    expect(roundSummary({ ...ROUND, days_to_close: 0 })).toBe(
      "Open, closes 21 Oct 2026 (closes today)",
    );
    expect(
      roundSummary({ ...ROUND, closes_on: null, days_to_close: null }),
    ).toBe("Open, no closing date given");
  });

  it("describes closed, upcoming and paused rounds", () => {
    expect(
      roundSummary({ ...ROUND, state: "CLOSED", closes_on: "2024-12-20" }),
    ).toBe("Closed 20 Dec 2024");
    expect(roundSummary({ ...ROUND, state: "UPCOMING", opens_on: null })).toBe(
      "Opening soon: date not announced",
    );
    expect(roundSummary({ ...ROUND, state: "PAUSED" })).toBe(
      "Paused to new applications",
    );
  });
});

describe("currentRound", () => {
  it("finds the round the API chose", () => {
    const program = {
      rounds: [ROUND],
      current_round_id: "r1",
    } as GrantProgramOut;
    expect(currentRound(program)).toBe(ROUND);
    expect(currentRound({ ...program, current_round_id: null })).toBeNull();
  });
});
