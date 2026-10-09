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
  /** The reports this project can make, when there is more than one (first is the default). */
  templates?: ReportTemplate[];
  pollMs?: number;
};

export type ReportTemplate = { key: string; title: string; description: string };

const FORMATS: OutputFormat[] = ["PDF", "DOCX", "HTML"];

/** The reports each kind of project can make (the API lists the same per vertical). */
export const REPORT_TEMPLATES: Record<string, ReportTemplate[]> = {
  VESSEL: [
    {
      key: "VESSEL_PATHWAY",
      title: "Approvals pathway",
      description:
        "The certificates and approvals we found, your checklists, who can help, the answers it " +
        "relies on, missing information, sources and review status.",
    },
    {
      key: "SMS",
      title: "Safety management system (draft)",
      description:
        "What you have written in the SMS builder under Marine Order 504's headings, with the " +
        "parts still to write. It is your document: nobody has approved it.",
    },
  ],
};

const DEFAULT_TEMPLATE: ReportTemplate = {
  key: "",
  title: "Download this report",
  description:
    "The file shows the date, your project reference, the answers it relies on, missing " +
    "information, sources and that no professional has reviewed it yet.",
};

/** Make the assessment's reports as PDF, Word or HTML files and download them. */
export function ReportDownloads(props: Props) {
  const { organisationId, assessmentId, canWrite, pollMs } = props;
  const templates =
    props.templates && props.templates.length > 0 ? props.templates : [DEFAULT_TEMPLATE];
  const [generated, setGenerated] = useState(props.generated);
  const [working, setWorking] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function make(template: string, format: OutputFormat) {
    setWorking(`${template}:${format}`);
    setError(null);
    const started = await apiRequest<GeneratedDocumentOut>(
      "POST",
      `/organisations/${organisationId}/assessments/${assessmentId}/documents`,
      template ? { format, template } : { format },
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

  const several = templates.length > 1;
  return (
    <section className="panel" aria-labelledby="report-files-title">
      <h2 id="report-files-title" className="section-title">
        {several ? "Download reports" : DEFAULT_TEMPLATE.title}
      </h2>
      <FormError message={error} />
      {templates.map((template) => {
        const latest = FORMATS.map((f) =>
          generated.find(
            (g) =>
              g.format === f &&
              g.status === "READY" &&
              (!template.key || g.template_key === template.key),
          ),
        ).filter((g): g is GeneratedDocumentOut => g !== undefined);
        return (
          <div key={template.key || "default"} className={several ? "report-template" : undefined}>
            {several ? <h3 className="subsection-title">{template.title}</h3> : null}
            <p className="muted">{template.description}</p>
            {canWrite ? (
              <div className="button-row tight">
                {FORMATS.map((format) => (
                  <button
                    key={format}
                    type="button"
                    className="button button-secondary"
                    disabled={working !== null}
                    aria-label={
                      several ? `Make ${template.title} as ${FORMAT_LABELS[format]}` : undefined
                    }
                    onClick={() => make(template.key, format)}
                  >
                    {working === `${template.key}:${format}`
                      ? "Making…"
                      : `Make ${FORMAT_LABELS[format]}`}
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
          </div>
        );
      })}
    </section>
  );
}
