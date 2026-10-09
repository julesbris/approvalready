"use client";

import type {
  DocumentOut,
  InspectionDetailOut,
  InspectionItemOut,
} from "@approvalready/shared-types";
import { type ChangeEvent, useState } from "react";

import { FormError } from "@/components/auth/FormStatus";
import { apiRequest, apiUpload } from "@/lib/client-api";
import { formatDateTime } from "@/lib/labels";
import {
  CONDITIONS,
  INSPECTION_KIND_LABELS,
  INSPECTION_STATUS_LABELS,
  byRoom,
} from "@/lib/property";

type Props = {
  organisationId: string;
  projectId: string;
  inspection: InspectionDetailOut;
  canWrite: boolean;
};

const SCAN_WAIT_MS = 2000;
const SCAN_TRIES = 15;

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** A room-by-room inspection, laid out for a phone: tap a condition, add a note or a photo. */
export function InspectionRunner({ organisationId, projectId, canWrite, ...props }: Props) {
  const [inspection, setInspection] = useState(props.inspection);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const org = `/organisations/${organisationId}`;
  const open = canWrite && !["COMPLETED", "CANCELLED"].includes(inspection.status);
  const rooms = byRoom(inspection.items);

  function replace(item: InspectionItemOut) {
    setInspection((i) => {
      const items = i.items.map((x) => (x.id === item.id ? item : x));
      return {
        ...i,
        items,
        items_checked: items.filter((x) => x.condition).length,
        status: i.status === "SCHEDULED" ? "IN_PROGRESS" : i.status,
      };
    });
  }

  async function save(item: InspectionItemOut, body: Record<string, unknown>) {
    setBusy(item.id);
    setError(null);
    const result = await apiRequest<InspectionItemOut>(
      "PATCH",
      `${org}/inspection-items/${item.id}`,
      body,
    );
    setBusy(null);
    if (!result.ok) {
      setError(result.message);
      return false;
    }
    replace(result.data);
    return true;
  }

  async function addPhoto(item: InspectionItemOut, event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setBusy(item.id);
    setError(null);
    const uploaded = await apiUpload<DocumentOut>(`${org}/projects/${projectId}/documents`, file);
    if (!uploaded.ok) {
      setBusy(null);
      setError(uploaded.message);
      return;
    }
    // The photo is virus-checked before it can be attached; wait for the check.
    const photos = [...item.photo_document_ids, uploaded.data.id];
    for (let attempt = 0; attempt < SCAN_TRIES; attempt += 1) {
      const result = await apiRequest<InspectionItemOut>(
        "PATCH",
        `${org}/inspection-items/${item.id}`,
        { photo_document_ids: photos },
      );
      if (result.ok) {
        replace(result.data);
        setBusy(null);
        return;
      }
      if (result.code !== "document_not_scanned") {
        setBusy(null);
        setError(result.message);
        return;
      }
      await wait(SCAN_WAIT_MS);
    }
    setBusy(null);
    setError("The photo is still being checked. Try attaching it again in a minute.");
  }

  async function setStatus(status: string) {
    setBusy("inspection");
    setError(null);
    const result = await apiRequest<InspectionDetailOut>(
      "PATCH",
      `${org}/inspections/${inspection.id}`,
      { status },
    );
    setBusy(null);
    if (!result.ok) setError(result.message);
    else setInspection(result.data);
  }

  return (
    <div className="workspace inspection">
      <section className="page-head" aria-labelledby="inspection-title">
        <div>
          <h1 id="inspection-title" className="page-title">
            {INSPECTION_KIND_LABELS[inspection.kind]} inspection
          </h1>
          <p className="muted">
            {formatDateTime(inspection.scheduled_at)} ·{" "}
            <span className="status">{INSPECTION_STATUS_LABELS[inspection.status]}</span> ·{" "}
            {inspection.items_checked} of {inspection.items_total} checked
          </p>
        </div>
      </section>
      <FormError message={error} />
      <nav aria-label="Rooms" className="room-nav">
        {rooms.map(([room], index) => (
          <a key={room} href={`#room-${index}`}>
            {room}
          </a>
        ))}
      </nav>
      {rooms.map(([room, items], index) => (
        <section key={room} id={`room-${index}`} className="panel" aria-labelledby={`room-${index}-title`}>
          <h2 id={`room-${index}-title`} className="section-title">
            {room}
          </h2>
          <ul className="inspection-items">
            {items.map((item) => (
              <li key={item.id} className="inspection-item">
                <p className="inspection-item-name">{item.item}</p>
                <div className="condition-buttons" role="group" aria-label={`${room}: ${item.item}`}>
                  {CONDITIONS.map(([value, label]) => (
                    <button
                      key={value}
                      type="button"
                      className={item.condition === value ? "button" : "button button-secondary"}
                      aria-pressed={item.condition === value}
                      disabled={!open || busy !== null}
                      onClick={() => save(item, { condition: value })}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                {open ? (
                  <>
                    <label>
                      <span className="visually-hidden">Notes on {item.item}</span>
                      <input
                        placeholder="Notes"
                        maxLength={1000}
                        value={notes[item.id] ?? item.notes ?? ""}
                        onChange={(e) => setNotes((n) => ({ ...n, [item.id]: e.target.value }))}
                        onBlur={() => {
                          const value = notes[item.id];
                          if (value !== undefined && value !== (item.notes ?? "")) {
                            save(item, { notes: value.trim() || null });
                          }
                        }}
                      />
                    </label>
                    <label className="button-link photo-input">
                      {busy === item.id ? "Saving…" : "Add a photo"}
                      <input
                        type="file"
                        accept="image/*"
                        capture="environment"
                        className="visually-hidden"
                        disabled={busy !== null}
                        onChange={(e) => addPhoto(item, e)}
                      />
                    </label>
                  </>
                ) : item.notes ? (
                  <p className="muted">{item.notes}</p>
                ) : null}
                {item.photo_document_ids.length > 0 ? (
                  <p className="muted">
                    {item.photo_document_ids.length} photo
                    {item.photo_document_ids.length === 1 ? "" : "s"}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ))}
      {canWrite ? (
        <div className="button-row">
          {open ? (
            <button
              type="button"
              className="button"
              disabled={busy !== null}
              onClick={() => setStatus("COMPLETED")}
            >
              Finish the inspection
            </button>
          ) : null}
          {inspection.status === "COMPLETED" ? (
            <button
              type="button"
              className="button-link"
              disabled={busy !== null}
              onClick={() => setStatus("IN_PROGRESS")}
            >
              Reopen
            </button>
          ) : null}
        </div>
      ) : null}
      <p className="hint">
        This is your own record. Your state may also have an official condition report form to
        give the tenant; your rental checklist says which.
      </p>
    </div>
  );
}
