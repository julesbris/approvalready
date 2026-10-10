import type {
  BenchmarksOut,
  FunnelOut,
  MarketPartnerOut,
  MarketTotalsOut,
} from "@approvalready/shared-types";
import Link from "next/link";

import { PERIODS, PERIOD_LABELS, type Period, duration, percent } from "@/lib/analytics";
import { money } from "@/lib/leads";

/** Links to the same page for each period. */
export function PeriodNav({ path, current }: { path: string; current: Period }) {
  return (
    <nav aria-label="Period" className="admin-nav">
      {PERIODS.map((p) => (
        <Link
          key={p}
          href={`${path}?months=${p}`}
          aria-current={p === current ? "page" : undefined}
        >
          {PERIOD_LABELS[p]}
        </Link>
      ))}
    </nav>
  );
}

/** Headline figures as a list of label and value pairs. */
export function Stats({ items }: { items: [string, string][] }) {
  return (
    <dl className="stat-grid">
      {items.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function partnerStats(t: FunnelOut): [string, string][] {
  return [
    ["Referrals offered", String(t.offered)],
    ["Accepted", `${t.accepted} (${percent(t.accept_rate)})`],
    ["Answered within 48 hours", percent(t.answered_within_48h_rate)],
    ["Typical reply time", duration(t.median_response_hours)],
    ["Won", `${t.won} of ${t.won + t.lost} decided (${percent(t.win_rate)})`],
    ["Fees paid", money(t.fees_cents)],
  ];
}

/** One partner's funnel, one row per category, area or month. */
export function FunnelTable<T extends FunnelOut>({
  rows,
  heading,
  label,
  caption,
}: {
  rows: T[];
  heading: string;
  label: (row: T) => string;
  caption: string;
}) {
  if (rows.length === 0) return <p className="muted">No referrals in this period.</p>;
  return (
    <div className="table-scroll">
      <table className="usage-table">
        <caption className="visually-hidden">{caption}</caption>
        <thead>
          <tr>
            <th scope="col">{heading}</th>
            <th scope="col">Offered</th>
            <th scope="col">Accepted</th>
            <th scope="col">Declined</th>
            <th scope="col">Missed</th>
            <th scope="col">Quoted</th>
            <th scope="col">Won</th>
            <th scope="col">Lost</th>
            <th scope="col">Typical reply</th>
            <th scope="col">Fees</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={label(row)}>
              <th scope="row">{label(row)}</th>
              <td>{row.offered}</td>
              <td>
                {row.accepted} <span className="muted">({percent(row.accept_rate)})</span>
              </td>
              <td>{row.declined}</td>
              <td>{row.missed}</td>
              <td>{row.quoted}</td>
              <td>{row.won}</td>
              <td>{row.lost}</td>
              <td>{duration(row.median_response_hours)}</td>
              <td>{money(row.fees_cents)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Your figure next to other partners' median (withheld below the threshold). */
export function BenchmarkTable({
  mine,
  bench,
}: {
  mine: Map<string, FunnelOut>;
  bench: BenchmarksOut;
}) {
  return (
    <>
      <p className="muted">
        The middle figure among other partners offered referrals in the same category and period. To
        protect every partner&apos;s figures, we only show one when at least {bench.min_partners}{" "}
        other partners contribute to it, and we never show who they are or how many there are.
      </p>
      <div className="table-scroll">
        <table className="usage-table">
          <caption className="visually-hidden">You compared with other partners</caption>
          <thead>
            <tr>
              <th scope="col">Category</th>
              <th scope="col">Accepted: you / others</th>
              <th scope="col">Won: you / others</th>
              <th scope="col">Typical reply: you / others</th>
            </tr>
          </thead>
          <tbody>
            {bench.rows.map((row) => {
              const you = mine.get(row.category_key ?? "");
              return (
                <tr key={row.category_key ?? "all"}>
                  <th scope="row">{row.category_label}</th>
                  <td>
                    {percent(you?.accept_rate)} /{" "}
                    {others(percent(row.accept_rate), row.accept_rate)}
                  </td>
                  <td>
                    {percent(you?.win_rate)} / {others(percent(row.win_rate), row.win_rate)}
                  </td>
                  <td>
                    {duration(you?.median_response_hours)} /{" "}
                    {others(duration(row.median_response_hours), row.median_response_hours)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

function others(text: string, value: number | null | undefined) {
  return value === null || value === undefined ? (
    <span className="muted">not enough partners yet</span>
  ) : (
    text
  );
}

export function marketStats(t: MarketTotalsOut): [string, string][] {
  return [
    ["Requests (one per category)", String(t.leads)],
    ["Found a partner", `${t.found_partner} (${percent(t.found_partner_rate)})`],
    ["No partner available", String(t.no_partner_available)],
    ["Ended with no partner", String(t.expired_unclaimed)],
    ["Typical time to first acceptance", duration(t.median_hours_to_first_accept)],
    ["Won", `${t.won} of ${t.won + t.lost} decided (${percent(t.win_rate)})`],
    ["Fees charged", money(t.fees_cents)],
    ["Fees refunded", money(t.refunded_cents)],
  ];
}

/** Staff: the marketplace by category, area or month. */
export function MarketTable<T extends MarketTotalsOut>({
  rows,
  heading,
  label,
  caption,
}: {
  rows: T[];
  heading: string;
  label: (row: T) => string;
  caption: string;
}) {
  if (rows.length === 0) return <p className="muted">No requests in this period.</p>;
  return (
    <div className="table-scroll">
      <table className="usage-table">
        <caption className="visually-hidden">{caption}</caption>
        <thead>
          <tr>
            <th scope="col">{heading}</th>
            <th scope="col">Requests</th>
            <th scope="col">No partner available</th>
            <th scope="col">Found a partner</th>
            <th scope="col">Ended with none</th>
            <th scope="col">Open</th>
            <th scope="col">Time to first acceptance</th>
            <th scope="col">Won / lost</th>
            <th scope="col">Fees</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={label(row)}>
              <th scope="row">{label(row)}</th>
              <td>{row.leads}</td>
              <td>{row.no_partner_available}</td>
              <td>
                {row.found_partner}{" "}
                <span className="muted">({percent(row.found_partner_rate)})</span>
              </td>
              <td>{row.expired_unclaimed}</td>
              <td>{row.open}</td>
              <td>{duration(row.median_hours_to_first_accept)}</td>
              <td>
                {row.won} / {row.lost}
              </td>
              <td>{money(row.fees_cents)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function MarketPartners({ partners }: { partners: MarketPartnerOut[] }) {
  if (partners.length === 0) return <p className="muted">No referrals offered in this period.</p>;
  return (
    <div className="table-scroll">
      <table className="usage-table">
        <caption className="visually-hidden">Partners by referrals offered</caption>
        <thead>
          <tr>
            <th scope="col">Partner</th>
            <th scope="col">Offered</th>
            <th scope="col">Accepted</th>
            <th scope="col">Declined</th>
            <th scope="col">Missed</th>
            <th scope="col">Within 48 hours</th>
            <th scope="col">Typical reply</th>
            <th scope="col">Won / lost</th>
            <th scope="col">Fees</th>
          </tr>
        </thead>
        <tbody>
          {partners.map((p) => (
            <tr key={p.partner_id}>
              <th scope="row">
                <Link href={`/admin/partners/${p.partner_id}`}>{p.name}</Link>
                {p.status !== "ACTIVE" ? (
                  <span className="muted"> ({p.status.toLowerCase()})</span>
                ) : null}
              </th>
              <td>{p.offered}</td>
              <td>
                {p.accepted} <span className="muted">({percent(p.accept_rate)})</span>
              </td>
              <td>{p.declined}</td>
              <td>{p.missed}</td>
              <td>{percent(p.answered_within_48h_rate)}</td>
              <td>{duration(p.median_response_hours)}</td>
              <td>
                {p.won} / {p.lost}
              </td>
              <td>{money(p.fees_cents)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
