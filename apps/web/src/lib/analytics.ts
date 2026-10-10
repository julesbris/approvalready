/** Marketplace analytics (Milestone 16): periods, rates, times and months in plain words. */

export const PERIODS = [1, 3, 6, 12] as const;
export type Period = (typeof PERIODS)[number];

export const PERIOD_LABELS: Record<Period, string> = {
  1: "This month",
  3: "3 months",
  6: "6 months",
  12: "12 months",
};

/** The period asked for in the address, or 6 months. */
export function parsePeriod(value: string | undefined): Period {
  const n = Number(value);
  return (PERIODS as readonly number[]).includes(n) ? (n as Period) : 6;
}

/** 0.5 → "50%"; nothing to divide by → "–". */
export function percent(rate: number | null | undefined): string {
  if (rate === null || rate === undefined) return "–";
  return `${Math.round(rate * 100)}%`;
}

/** Hours as "35 min", "5.5 hours" or "3 days"; none → "–". */
export function duration(hours: number | null | undefined): string {
  if (hours === null || hours === undefined) return "–";
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))} min`;
  if (hours < 48) {
    const h = Math.round(hours * 10) / 10;
    return `${h} ${h === 1 ? "hour" : "hours"}`;
  }
  return `${Math.round(hours / 24)} days`;
}

/** "2026-10" → "Oct 2026". */
export function monthLabel(month: string): string {
  const year = Number(month.slice(0, 4));
  const m = Number(month.slice(5, 7));
  const name = new Date(Date.UTC(year, m - 1, 1)).toLocaleString("en-AU", {
    month: "short",
    timeZone: "UTC",
  });
  return `${name} ${year}`;
}
