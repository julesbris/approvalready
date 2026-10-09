/**
 * GrantReady presentation: plain-language labels for match statuses and round states, and
 * one-line summaries of a program's money and its rounds. Pure, so it is unit tested.
 */

import type {
  GrantProgramOut,
  GrantRoundOut,
  MatchStatus,
  RoundStatus,
} from "@approvalready/shared-types";

import { formatDate } from "@/lib/questionnaire";

export const MATCH_LABELS: Record<MatchStatus, string> = {
  STRONG_MATCH: "Meets every criterion we check",
  POSSIBLE_MATCH: "Might be eligible",
  NEEDS_INFORMATION: "We need more information",
  NOT_ELIGIBLE: "Not eligible on your answers",
};

export const MATCH_HELP: Record<MatchStatus, string> = {
  STRONG_MATCH:
    "Your answers meet every criterion we encode for this program. Programs also assess things " +
    "we can't check, so this doesn't mean an application will succeed.",
  POSSIBLE_MATCH:
    "Your answers meet the criteria we check, but a source behind them needs review. Confirm " +
    "with the program before you rely on it.",
  NEEDS_INFORMATION:
    "Answer the questions below and run a new assessment to finish this check.",
  NOT_ELIGIBLE:
    "At least one criterion isn't met on your answers. Check the ones marked below.",
};

export const ROUND_LABELS: Record<RoundStatus, string> = {
  OPEN: "Open",
  UPCOMING: "Opening soon",
  PAUSED: "Paused",
  CLOSED: "Closed",
};

export const CRITERION_LABELS: Record<string, string> = {
  MATCH: "Met",
  NO_MATCH: "Not met",
  UNKNOWN: "Not answered",
};

const DOLLARS = new Intl.NumberFormat("en-AU", {
  style: "currency",
  currency: "AUD",
  maximumFractionDigits: 0,
});

/** "$20,000 to $80,000", "Up to $75,000", "From $50,000" or null. */
export function amountRange(
  min: number | null,
  max: number | null,
): string | null {
  const f = (cents: number) => DOLLARS.format(cents / 100);
  if (min != null && max != null)
    return min === max ? f(min) : `${f(min)} to ${f(max)}`;
  if (max != null) return `Up to ${f(max)}`;
  if (min != null) return `From ${f(min)}`;
  return null;
}

/** e.g. "Open, closes 20 Oct 2026 (12 days left)" or "Closed 20 Dec 2024". */
export function roundSummary(round: GrantRoundOut): string {
  const state = ROUND_LABELS[round.state];
  switch (round.state) {
    case "OPEN": {
      if (!round.closes_on) return `${state}, no closing date given`;
      const left =
        round.days_to_close === 0
          ? "closes today"
          : `${round.days_to_close} day${round.days_to_close === 1 ? "" : "s"} left`;
      return `${state}, closes ${formatDate(round.closes_on)} (${left})`;
    }
    case "UPCOMING":
      return round.opens_on
        ? `${state}: opens ${formatDate(round.opens_on)}`
        : `${state}: date not announced`;
    case "CLOSED":
      return round.closes_on
        ? `${state} ${formatDate(round.closes_on)}`
        : state;
    default:
      return `${state} to new applications`;
  }
}

/** The round to show first (the API picks it: open, else upcoming, else the latest). */
export function currentRound(program: GrantProgramOut): GrantRoundOut | null {
  return program.rounds.find((r) => r.id === program.current_round_id) ?? null;
}
