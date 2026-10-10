import type { AIUsageOut, PromptVersionOut } from "@approvalready/shared-types";

import { formatDateTime } from "@/lib/labels";

/** Dollars from millionths of a dollar, to the cent (fractions of a cent shown as < $0.01). */
export function formatMicros(micros: number): string {
  if (micros > 0 && micros < 10_000) return "< $0.01";
  return `$${(micros / 1_000_000).toFixed(2)}`;
}

const TASK_LABELS: Record<string, string> = {
  ASSESSMENT_EXPLANATION: "Plain-language explanations",
  GRANT_DRAFT: "Grant application notes",
};

export function AIUsage({ usage, prompts }: { usage: AIUsageOut; prompts: PromptVersionOut[] }) {
  const total = usage.rows.reduce((sum, r) => sum + r.cost_micros, 0);
  return (
    <>
      <section className="panel" aria-labelledby="ai-provider-title">
        <h2 id="ai-provider-title" className="section-title">
          Provider
        </h2>
        <p>
          {usage.enabled
            ? `Switched on: ${usage.provider}${usage.model ? ` (${usage.model})` : ""}.`
            : "Switched off (AI_PROVIDER=none). Customers don't see AI drafts."}
        </p>
      </section>
      <section className="panel" aria-labelledby="ai-usage-title">
        <h2 id="ai-usage-title" className="section-title">
          Since {formatDateTime(usage.since)}
        </h2>
        {usage.rows.length === 0 ? (
          <p className="muted">No calls yet.</p>
        ) : (
          <table className="usage-table">
            <thead>
              <tr>
                <th>Task</th>
                <th>Provider and model</th>
                <th>Outcome</th>
                <th>Calls</th>
                <th>Tokens in / out</th>
                <th>Cost</th>
              </tr>
            </thead>
            <tbody>
              {usage.rows.map((r) => (
                <tr key={`${r.provider}:${r.model}:${r.task}:${r.status}`}>
                  <td>{TASK_LABELS[r.task] ?? r.task}</td>
                  <td>
                    {r.provider} · {r.model}
                  </td>
                  <td>{r.status}</td>
                  <td>{r.calls}</td>
                  <td>
                    {r.request_tokens.toLocaleString("en-AU")} /{" "}
                    {r.response_tokens.toLocaleString("en-AU")}
                  </td>
                  <td>{formatMicros(r.cost_micros)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="muted">
          Total {formatMicros(total)} (US dollars, from the configured prices per million tokens).
        </p>
      </section>
      <section className="panel" aria-labelledby="ai-prompts-title">
        <h2 id="ai-prompts-title" className="section-title">
          Prompts
        </h2>
        {prompts.map((p) => (
          <details key={p.id}>
            <summary>
              {TASK_LABELS[p.task] ?? p.task} · version {p.version} ·{" "}
              {p.status === "PUBLISHED" ? "in use" : "retired"} · answers as{" "}
              {p.output_schema_name} v{p.output_schema_version}
            </summary>
            <pre className="prompt-text">{p.system_prompt}</pre>
          </details>
        ))}
      </section>
    </>
  );
}
