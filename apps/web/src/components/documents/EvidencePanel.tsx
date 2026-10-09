"use client";

import type {
  DocumentOut,
  EvidenceOut,
  EvidenceRequirementOut,
} from "@approvalready/shared-types";
import { type ChangeEvent, useState } from "react";

import { FormError } from "@/components/auth/FormStatus";
import { DocumentRow } from "@/components/documents/DocumentsPanel";
import { apiRequest } from "@/lib/client-api";
import { ACCEPT, uploadDocument, waitForScan } from "@/lib/documents";

type Props = {
  organisationId: string;
  projectId: string;
  requirements: EvidenceRequirementOut[];
  evidence: EvidenceOut[];
  documents: DocumentOut[];
  canWrite: boolean;
  pollMs?: number;
};

const EVIDENCE_LABELS: Record<EvidenceOut["status"], string> = {
  SUBMITTED: "Provided",
  ACCEPTED: "Accepted by a reviewer",
  REJECTED: "Not accepted by a reviewer",
};

/** For each piece of evidence the assessment says you'll need, the files you've provided. */
export function EvidencePanel(props: Props) {
  const { organisationId, projectId, requirements, canWrite, pollMs } = props;
  const [evidence, setEvidence] = useState(props.evidence);
  const [documents, setDocuments] = useState(props.documents);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (requirements.length === 0) return null;
  const org = `/organisations/${organisationId}`;

  async function attach(requirementId: string, documentId: string) {
    const result = await apiRequest<EvidenceOut>("POST", `${org}/evidence`, {
      evidence_requirement_id: requirementId,
      uploaded_document_id: documentId,
    });
    if (!result.ok) {
      setError(result.message);
      return;
    }
    setEvidence((list) => [...list, result.data]);
  }

  async function choose(requirementId: string, documentId: string) {
    if (!documentId) return;
    setBusy(true);
    setError(null);
    await attach(requirementId, documentId);
    setBusy(false);
  }

  async function upload(requirementId: string, event: ChangeEvent<HTMLInputElement>) {
    const input = event.currentTarget;
    const file = input.files?.[0];
    if (!file) return;
    setBusy(true);
    setError(null);
    const uploaded = await uploadDocument(organisationId, projectId, file);
    input.value = "";
    if (!uploaded.ok) {
      setBusy(false);
      setError(uploaded.message);
      return;
    }
    // Evidence takes virus-checked files only, so wait for the check first.
    const checked =
      uploaded.data.scan_status === "PENDING"
        ? await waitForScan(organisationId, uploaded.data, pollMs)
        : uploaded;
    if (!checked.ok) {
      setBusy(false);
      setError(checked.message);
      return;
    }
    setDocuments((list) => [...list, checked.data]);
    if (checked.data.scan_status === "CLEAN") {
      await attach(requirementId, checked.data.id);
    } else if (checked.data.scan_status === "PENDING") {
      setError("The virus check is taking a while. Attach the file from the list once it's ready.");
    } else {
      setError("That file didn't pass the virus check, so it can't be used.");
    }
    setBusy(false);
  }

  async function withdraw(item: EvidenceOut) {
    setBusy(true);
    setError(null);
    const result = await apiRequest("DELETE", `${org}/evidence/${item.id}`);
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    setEvidence((list) => list.filter((e) => e.id !== item.id));
  }

  return (
    <section className="panel" aria-labelledby="evidence-title">
      <h2 id="evidence-title" className="section-title">
        Your evidence
      </h2>
      <p className="muted">
        Attach the files that show each of these. They stay private to your organisation, and a
        professional reviewer you ask to check this assessment can see them.
      </p>
      <FormError message={error} />
      <ul className="finding-list">
        {requirements.map((req) => {
          const provided = evidence.filter((e) => e.evidence_requirement_id === req.id);
          const available = documents.filter(
            (d) => d.scan_status === "CLEAN" && !provided.some((e) => e.document.id === d.id),
          );
          return (
            <li key={req.id} className="finding">
              <h3 className="finding-title">{req.title}</h3>
              {req.detail ? <p className="muted">{req.detail}</p> : null}
              {provided.length === 0 ? <p className="muted">Nothing attached yet.</p> : null}
              <ul className="task-list">
                {provided.map((item) => (
                  <DocumentRow
                    key={item.id}
                    organisationId={organisationId}
                    document={item.document}
                  >
                    <span className="badge">{EVIDENCE_LABELS[item.status]}</span>
                    {item.review_note ? (
                      <span className="muted">Reviewer: {item.review_note}</span>
                    ) : null}
                    {canWrite && item.status === "SUBMITTED" ? (
                      <button
                        type="button"
                        className="button-link"
                        disabled={busy}
                        onClick={() => withdraw(item)}
                        aria-label={`Remove ${item.document.filename} from ${req.title}`}
                      >
                        Remove
                      </button>
                    ) : null}
                  </DocumentRow>
                ))}
              </ul>
              {canWrite ? (
                <div className="form inline-form">
                  {available.length > 0 ? (
                    <label>
                      Attach a project file
                      <select
                        value=""
                        disabled={busy}
                        onChange={(e) => choose(req.id, e.target.value)}
                      >
                        <option value="">Choose…</option>
                        {available.map((d) => (
                          <option key={d.id} value={d.id}>
                            {d.filename}
                          </option>
                        ))}
                      </select>
                    </label>
                  ) : null}
                  <label>
                    Upload a file
                    <input
                      type="file"
                      accept={ACCEPT}
                      disabled={busy}
                      onChange={(e) => upload(req.id, e)}
                    />
                  </label>
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
