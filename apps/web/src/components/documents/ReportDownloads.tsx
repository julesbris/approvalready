"use client";

import type { GeneratedDocumentOut, OutputFormat } from "@approvalready/shared-types";
import { useState } from "react";

import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";
import { FORMAT_LABELS, formatBytes, generatedUrl, waitForReport } from "@/lib/documents";
import { formatDateTime } from "@/lib/labels";

type Props = {
  organisationId: string;
  assessmentId: string;
  generated: GeneratedDocumentOut[];
  canWrite: boolean;
  pollMs?: number;
};

const FORMATS: OutputFormat[] = ["PDF", "DOCX", "HTML"];

/** Make the assessment report as a PDF, Word or HTML file and download it. */
export function ReportDownloads(props: Props) {
  const { organisationId, assessmentId, canWrite, pollMs } = props;
  const [generated, setGenerated] = useState(props.generated);
  const [working, setWorking] = useState<OutputFormat | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function make(format: OutputFormat) {
    setWorking(format);
    setError(null);
    const started = await apiRequest<GeneratedDocumentOut>(
      "POST",
      `/organisations/${organisationId}/assessments/${assessmentId}/documents`,
      { format },
    );
    if (!started.ok) {
      setWorking(null);
      setError(started.message);
      return;
    }
    setGenerated((list) => [started.data, ...list]);
    const done =
      started.data.status === "PENDING"
        ? await waitForReport(organisationId, started.data, pollMs)
        : started;
    setWorking(null);
    if (!done.ok) {
      setError(done.message);
      return;
    }
    setGenerated((list) => list.map((g) => (g.id === done.data.id ? done.data : g)));
    if (done.data.status === "FAILED") setError(done.data.error ?? "The report couldn't be made.");
  }

  const latest = FORMATS.map((f) => generated.find((g) => g.format === f && g.status === "READY"))
    .filter((g): g is GeneratedDocumentOut => g !== undefined);

  return (
    <section className="panel" aria-labelledby="report-files-title">
      <h2 id="report-files-title" className="section-title">
        Download this report
      </h2>
      <p className="muted">
        The file shows the date, your project reference, the answers it relies on, missing
        information, sources and that no professional has reviewed it yet.
      </p>
      <FormError message={error} />
      {canWrite ? (
        <div className="button-row tight">
          {FORMATS.map((format) => (
            <button
              key={format}
              type="button"
              className="button button-secondary"
              disabled={working !== null}
              onClick={() => make(format)}
            >
              {working === format ? "Making…" : `Make ${FORMAT_LABELS[format]}`}
            </button>
          ))}
        </div>
      ) : null}
      {latest.length > 0 ? (
        <ul className="task-list">
          {latest.map((g) => (
            <li key={g.id} className="task">
              <a href={generatedUrl(organisationId, g.id)} download={g.filename}>
                {g.filename}
              </a>
              <span className="muted">
                {FORMAT_LABELS[g.format]}
                {g.size_bytes ? ` · ${formatBytes(g.size_bytes)}` : ""} · made{" "}
                {formatDateTime(g.completed_at ?? g.created_at)}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
