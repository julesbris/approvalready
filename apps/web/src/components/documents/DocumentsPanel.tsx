"use client";

import type { DocumentOut } from "@approvalready/shared-types";
import { type ChangeEvent, useState } from "react";

import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";
import {
  ACCEPT,
  SCAN_LABELS,
  documentUrl,
  formatBytes,
  uploadDocument,
  waitForScan,
} from "@/lib/documents";
import { formatDateTime } from "@/lib/labels";

type Props = {
  organisationId: string;
  projectId: string;
  documents: DocumentOut[];
  canWrite: boolean;
  /** Poll interval while a file is being checked (tests shorten it). */
  pollMs?: number;
};

export function DocumentRow({
  organisationId,
  document,
  children,
}: {
  organisationId: string;
  document: DocumentOut;
  children?: React.ReactNode;
}) {
  return (
    <li className="task">
      {document.scan_status === "CLEAN" ? (
        <a href={documentUrl(organisationId, document.id)} download={document.filename}>
          {document.filename}
        </a>
      ) : (
        <span>{document.filename}</span>
      )}
      <span className="muted">
        {formatBytes(document.size_bytes)} · {formatDateTime(document.created_at)}
        {document.scan_status === "CLEAN" ? "" : ` · ${SCAN_LABELS[document.scan_status]}`}
      </span>
      {children}
    </li>
  );
}

/** A project's files: upload, virus-check status, download and delete. */
export function DocumentsPanel({ organisationId, projectId, canWrite, pollMs, ...props }: Props) {
  const [documents, setDocuments] = useState(props.documents);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const replace = (doc: DocumentOut) =>
    setDocuments((list) => list.map((d) => (d.id === doc.id ? doc : d)));

  async function onFiles(event: ChangeEvent<HTMLInputElement>) {
    const input = event.currentTarget;
    const files = Array.from(input.files ?? []);
    if (files.length === 0) return;
    setBusy(true);
    setError(null);
    const pending: DocumentOut[] = [];
    for (const file of files) {
      const result = await uploadDocument(organisationId, projectId, file);
      if (!result.ok) {
        setError(`${file.name}: ${result.message}`);
        break;
      }
      setDocuments((list) => [...list, result.data]);
      if (result.data.scan_status === "PENDING") pending.push(result.data);
    }
    input.value = "";
    setBusy(false);
    for (const doc of pending) {
      const checked = await waitForScan(organisationId, doc, pollMs);
      if (checked.ok) replace(checked.data);
    }
  }

  async function remove(doc: DocumentOut) {
    if (!window.confirm(`Delete ${doc.filename}? This can't be undone.`)) return;
    setBusy(true);
    setError(null);
    const result = await apiRequest(
      "DELETE",
      `/organisations/${organisationId}/documents/${doc.id}`,
    );
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    setDocuments((list) => list.filter((d) => d.id !== doc.id));
  }

  return (
    <section className="panel" aria-labelledby="documents-title">
      <h2 id="documents-title" className="section-title">
        Documents
      </h2>
      <p className="muted">
        Plans, surveys, photos and letters for this project. Every file is checked for viruses
        before it can be opened, and only members of your organisation can see them.
      </p>
      <FormError message={error} />
      {documents.length === 0 ? <p className="muted">No files yet.</p> : null}
      <ul className="task-list">
        {documents.map((doc) => (
          <DocumentRow key={doc.id} organisationId={organisationId} document={doc}>
            {canWrite ? (
              <button
                type="button"
                className="button-link"
                disabled={busy}
                onClick={() => remove(doc)}
                aria-label={`Delete ${doc.filename}`}
              >
                Delete
              </button>
            ) : null}
          </DocumentRow>
        ))}
      </ul>
      {canWrite ? (
        <label className="form">
          <span>{busy ? "Uploading…" : "Add files"}</span>
          <input type="file" multiple accept={ACCEPT} disabled={busy} onChange={onFiles} />
          <span className="hint">
            PDF, Word, Excel, CSV, text or photos (JPEG, PNG, WebP, HEIC), up to 20 MB each.
          </span>
        </label>
      ) : null}
    </section>
  );
}
