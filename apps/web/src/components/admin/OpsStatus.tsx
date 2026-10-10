import type { OpsStatusOut } from "@approvalready/shared-types";

import { formatDateTime } from "@/lib/labels";
import { CHECK_STATE_LABELS, formatBytes, offsiteLabel } from "@/lib/ops";

const KIND_LABELS: Record<string, string> = {
  BACKUP: "Backup",
  RESTORE_CHECK: "Restore check",
};

function plural(n: number, one: string, many: string): string {
  return n === 1 ? one : many;
}

export function OpsStatus({ status }: { status: OpsStatusOut }) {
  const failing = status.checks.filter((c) => c.state === "FAILING").length;
  const others = status.alert_email_count;
  return (
    <>
      <section className="panel" aria-labelledby="ops-checks-title">
        <h2 id="ops-checks-title" className="section-title">
          {failing === 0
            ? "Everything is running"
            : `${failing} ${plural(failing, "needs", "need")} attention`}
        </h2>
        <p className="muted">
          Checked {formatDateTime(status.checked_at)}. The worker runs these checks every 10
          minutes and emails platform admins
          {others > 0 ? ` and ${others} other ${plural(others, "address", "addresses")}` : ""}{" "}
          when one needs attention.
        </p>
        <ul className="ops-checks" aria-label="Checks">
          {status.checks.map((c) => (
            <li key={c.key} className={`ops-check ops-${c.state.toLowerCase()}`}>
              <strong>{c.label}</strong>
              <span className="status">{CHECK_STATE_LABELS[c.state]}</span>
              <div className="muted">{c.detail}</div>
            </li>
          ))}
        </ul>
      </section>
      <section className="panel" aria-labelledby="ops-runs-title">
        <h2 id="ops-runs-title" className="section-title">
          Backups and restore checks
        </h2>
        {status.runs.length === 0 ? (
          <p className="muted">
            None yet. The backup service runs nightly at 2:30 am Brisbane time.
          </p>
        ) : (
          <div className="table-scroll">
            <table className="usage-table">
              <thead>
                <tr>
                  <th>Finished</th>
                  <th>What</th>
                  <th>Result</th>
                  <th>Database</th>
                  <th>Files</th>
                  <th>Off-site copy</th>
                </tr>
              </thead>
              <tbody>
                {status.runs.map((r) => (
                  <tr key={r.id}>
                    <td>{formatDateTime(r.finished_at)}</td>
                    <td>{KIND_LABELS[r.kind] ?? r.kind}</td>
                    <td>
                      {r.status === "OK" ? "OK" : "Failed"}
                      {r.detail ? <div className="muted">{r.detail}</div> : null}
                    </td>
                    <td>{r.kind === "BACKUP" ? formatBytes(r.database_bytes) : r.database_file}</td>
                    <td>{r.kind === "BACKUP" ? formatBytes(r.uploads_bytes) : "–"}</td>
                    <td>
                      {offsiteLabel(r, status.offsite_enabled)}
                      {r.offsite_error ? <div className="muted">{r.offsite_error}</div> : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <section className="panel" aria-labelledby="ops-setup-title">
        <h2 id="ops-setup-title" className="section-title">
          Set-up
        </h2>
        <ul>
          <li>
            Off-site copies:{" "}
            {status.offsite_enabled ? "on (BACKUP_S3_BUCKET)" : "off: backups stay on this server"}
          </li>
          <li>
            Error tracking:{" "}
            {status.error_tracking_enabled ? "on (SENTRY_DSN)" : "off: errors are in the logs only"}
          </li>
          <li>
            Version {status.version} ({status.git_sha})
          </li>
        </ul>
      </section>
    </>
  );
}
