"use client";

import type { DocumentOut } from "@approvalready/shared-types";
import { type ChangeEvent, useEffect, useState } from "react";

import { apiRequest } from "@/lib/client-api";
import { ACCEPT, SCAN_LABELS, uploadDocument, waitForScan } from "@/lib/documents";

export type FileContext = { organisationId: string; projectId: string };

type Props = FileContext & {
  id: string;
  value: unknown;
  maxFiles: number;
  disabled: boolean;
  describedBy?: string;
  onValue: (value: string[]) => void;
  pollMs?: number;
};

/** A FILE answer: the ids of uploads in this project, picked or uploaded here. */
export function FileAnswer(props: Props) {
  const { organisationId, projectId, maxFiles, disabled, onValue } = props;
  const chosen = Array.isArray(props.value) ? (props.value as string[]) : [];
  const [documents, setDocuments] = useState<DocumentOut[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void apiRequest<DocumentOut[]>(
      "GET",
      `/organisations/${organisationId}/projects/${projectId}/documents`,
    ).then((result) => {
      if (active) setDocuments(result.ok ? result.data : []);
    });
    return () => {
      active = false;
    };
  }, [organisationId, projectId]);

  const byId = new Map((documents ?? []).map((d) => [d.id, d]));
  const usable = (documents ?? []).filter(
    (d) => !chosen.includes(d.id) && (d.scan_status === "CLEAN" || d.scan_status === "PENDING"),
  );
  const full = chosen.length >= maxFiles;

  async function onFile(event: ChangeEvent<HTMLInputElement>) {
    const input = event.currentTarget;
    const file = input.files?.[0];
    if (!file) return;
    setBusy(true);
    setError(null);
    const result = await uploadDocument(organisationId, projectId, file);
    input.value = "";
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    setDocuments((list) => [...(list ?? []), result.data]);
    onValue([...chosen, result.data.id]);
    if (result.data.scan_status === "PENDING") {
      const checked = await waitForScan(organisationId, result.data, props.pollMs);
      if (checked.ok) {
        const updated = checked.data;
        setDocuments((list) => (list ?? []).map((d) => (d.id === updated.id ? updated : d)));
      }
    }
  }

  return (
    <div className="file-answer">
      {chosen.length > 0 ? (
        <ul className="plain-list">
          {chosen.map((id) => {
            const doc = byId.get(id);
            return (
              <li key={id}>
                {doc ? doc.filename : documents ? "A removed file" : "Loading…"}
                {doc && doc.scan_status !== "CLEAN" ? (
                  <span className="muted"> · {SCAN_LABELS[doc.scan_status]}</span>
                ) : null}{" "}
                <button
                  type="button"
                  className="button-link"
                  disabled={disabled || busy}
                  onClick={() => onValue(chosen.filter((x) => x !== id))}
                  aria-label={`Remove ${doc?.filename ?? "file"}`}
                >
                  Remove
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
      {!full ? (
        <>
          <input
            id={props.id}
            type="file"
            accept={ACCEPT}
            disabled={disabled || busy}
            aria-describedby={props.describedBy}
            onChange={onFile}
          />
          {usable.length > 0 ? (
            <select
              aria-label="Or choose a file already uploaded to this project"
              value=""
              disabled={disabled || busy}
              onChange={(e) => e.target.value && onValue([...chosen, e.target.value])}
            >
              <option value="">Or choose a file already uploaded…</option>
              {usable.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.filename}
                </option>
              ))}
            </select>
          ) : null}
        </>
      ) : (
        <p className="hint">You&apos;ve attached the most files this question takes.</p>
      )}
      {busy ? <p className="hint">Uploading…</p> : null}
      {error ? <p className="field-error">{error}</p> : null}
    </div>
  );
}
