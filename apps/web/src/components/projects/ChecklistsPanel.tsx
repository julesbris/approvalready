"use client";

import type {
  ChecklistDefinitionOut,
  ChecklistItemOut,
  ChecklistOut,
  ItemStatus,
} from "@approvalready/shared-types";
import { useState } from "react";

import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";

type Props = {
  organisationId: string;
  projectId: string;
  checklists: ChecklistOut[];
  definitions: ChecklistDefinitionOut[];
  canWrite: boolean;
};

/** Checklists on a project: added by the assessment or by the customer, ticked off item by
 * item. An item that doesn't apply is marked so, with a note if it is a required one. */
export function ChecklistsPanel({ organisationId, projectId, canWrite, ...props }: Props) {
  const [checklists, setChecklists] = useState(props.checklists);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [skipping, setSkipping] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const org = `/organisations/${organisationId}`;
  const available = props.definitions.filter((d) => !checklists.some((c) => c.key === d.key));

  function replaceItem(item: ChecklistItemOut) {
    setChecklists((list) =>
      list.map((c) => {
        if (c.id !== item.checklist_id) return c;
        const items = c.items.map((i) => (i.id === item.id ? item : i));
        return { ...c, items, done: items.filter((i) => i.status !== "OPEN").length };
      }),
    );
  }

  async function setStatus(item: ChecklistItemOut, status: ItemStatus, withNote?: string) {
    setBusy(true);
    setError(null);
    const result = await apiRequest<ChecklistItemOut>(
      "PATCH",
      `${org}/checklist-items/${item.id}`,
      { status, ...(withNote !== undefined ? { note: withNote } : {}) },
    );
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    replaceItem(result.data);
    setSkipping(null);
    setNote("");
  }

  async function add(key: string) {
    if (!key) return;
    setBusy(true);
    setError(null);
    const result = await apiRequest<ChecklistOut>(
      "POST",
      `${org}/projects/${projectId}/checklists`,
      { key },
    );
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    setChecklists((list) => [...list, result.data]);
  }

  async function remove(checklist: ChecklistOut) {
    setBusy(true);
    setError(null);
    const result = await apiRequest("DELETE", `${org}/checklists/${checklist.id}`);
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    setChecklists((list) => list.filter((c) => c.id !== checklist.id));
  }

  return (
    <section className="panel" aria-labelledby="checklists-title">
      <h2 id="checklists-title" className="section-title">
        Checklists
      </h2>
      <p className="muted">
        What to gather for each step. Your assessment adds the ones that apply; you can add
        others.
      </p>
      <FormError message={error} />
      {checklists.length === 0 ? <p className="muted">No checklists yet.</p> : null}
      {checklists.map((c) => (
        <div key={c.id} className="checklist">
          <h3 className="subsection-title">
            {c.title}{" "}
            <span className="badge">
              {c.done} of {c.total} done
            </span>
          </h3>
          <p className="muted">{c.description}</p>
          <ul className="task-list">
            {c.items.map((item) => (
              <li key={item.id} className={item.status === "OPEN" ? "task" : "task done"}>
                <label>
                  <input
                    type="checkbox"
                    checked={item.status === "DONE"}
                    disabled={!canWrite || busy || item.status === "NOT_APPLICABLE"}
                    onChange={() => setStatus(item, item.status === "DONE" ? "OPEN" : "DONE")}
                  />
                  <span>
                    {item.title}
                    {item.required ? null : <span className="muted"> (if it applies)</span>}
                  </span>
                </label>
                {item.detail ? <span className="muted">{item.detail}</span> : null}
                {item.status === "NOT_APPLICABLE" ? (
                  <span className="muted">
                    Doesn&apos;t apply{item.note ? `: ${item.note}` : ""}
                  </span>
                ) : null}
                {canWrite && item.status === "NOT_APPLICABLE" ? (
                  <button
                    type="button"
                    className="button-link"
                    disabled={busy}
                    onClick={() => setStatus(item, "OPEN")}
                  >
                    Undo
                  </button>
                ) : null}
                {canWrite && item.status === "OPEN" && skipping !== item.id ? (
                  <button
                    type="button"
                    className="button-link"
                    disabled={busy}
                    onClick={() =>
                      item.required ? setSkipping(item.id) : setStatus(item, "NOT_APPLICABLE")
                    }
                  >
                    Doesn&apos;t apply
                  </button>
                ) : null}
                {skipping === item.id ? (
                  <form
                    method="post"
                    className="form"
                    aria-label="Why this doesn't apply"
                    onSubmit={(e) => {
                      e.preventDefault();
                      setStatus(item, "NOT_APPLICABLE", note.trim());
                    }}
                  >
                    <label>
                      Why doesn&apos;t it apply?
                      <input
                        value={note}
                        required
                        maxLength={1000}
                        onChange={(e) => setNote(e.target.value)}
                      />
                    </label>
                    <div className="button-row tight">
                      <button type="submit" className="button button-secondary" disabled={busy}>
                        Save
                      </button>
                      <button
                        type="button"
                        className="button-link"
                        onClick={() => setSkipping(null)}
                      >
                        Cancel
                      </button>
                    </div>
                  </form>
                ) : null}
              </li>
            ))}
          </ul>
          <p className="hint">
            From:{" "}
            {c.sources.map((s, i) => (
              <span key={s.url}>
                {i > 0 ? "; " : null}
                <a href={s.url} target="_blank" rel="noreferrer">
                  {s.title}
                </a>{" "}
                ({s.organisation})
              </span>
            ))}
            . A summary of the source, not its wording.
          </p>
          {canWrite && c.origin === "USER" ? (
            <button
              type="button"
              className="button-link"
              disabled={busy}
              onClick={() => remove(c)}
            >
              Remove this checklist
            </button>
          ) : null}
        </div>
      ))}
      {canWrite && available.length > 0 ? (
        <label>
          Add a checklist
          <select value="" disabled={busy} onChange={(e) => add(e.target.value)}>
            <option value="">Choose…</option>
            {available.map((d) => (
              <option key={d.key} value={d.key}>
                {d.title}
              </option>
            ))}
          </select>
        </label>
      ) : null}
    </section>
  );
}
