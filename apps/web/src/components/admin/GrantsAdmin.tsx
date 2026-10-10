"use client";

import type {
  GrantProgramOut,
  GrantRoundOut,
  RoundStatus,
  SourceReferenceOut,
} from "@approvalready/shared-types";
import { type FormEvent, useState } from "react";

import { useAction } from "@/components/admin/useAction";
import { FormError } from "@/components/auth/FormStatus";
import { VERIFICATION_LABELS } from "@/lib/assessment";
import { apiRequest } from "@/lib/client-api";
import { ROUND_LABELS, amountRange, roundSummary } from "@/lib/grants";

const STATUSES: RoundStatus[] = ["UPCOMING", "OPEN", "PAUSED", "CLOSED"];

function text(form: FormData, name: string): string | null {
  const value = String(form.get(name) ?? "").trim();
  return value === "" ? null : value;
}

/** Fields shared by "add a round" and "update this round". */
function RoundFields({
  round,
  references,
}: {
  round?: GrantRoundOut;
  references: SourceReferenceOut[];
}) {
  return (
    <>
      <label>
        Round name
        <input
          name="title"
          required
          maxLength={200}
          defaultValue={round?.title}
        />
      </label>
      <label>
        Status the source gives
        <select name="status" required defaultValue={round?.status ?? ""}>
          <option value="" disabled>
            Choose…
          </option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {ROUND_LABELS[s]}
            </option>
          ))}
        </select>
      </label>
      <div className="field-row">
        <label>
          Opens (optional)
          <input
            name="opens_on"
            type="date"
            defaultValue={round?.opens_on ?? ""}
          />
        </label>
        <label>
          Closes (optional)
          <input
            name="closes_on"
            type="date"
            defaultValue={round?.closes_on ?? ""}
          />
        </label>
      </div>
      <label>
        Note on the dates (optional)
        <input
          name="dates_note"
          maxLength={500}
          defaultValue={round?.dates_note ?? ""}
          placeholder="e.g. closes 5pm AEST; tier 2 closed early"
        />
      </label>
      <label>
        Source these dates come from
        <select
          name="source_reference_id"
          required
          defaultValue={round?.source.reference_id ?? ""}
        >
          <option value="" disabled>
            Choose a source reference…
          </option>
          {references.map((r) => (
            <option key={r.id} value={r.id}>
              {r.citation} ({r.organisation_name},{" "}
              {VERIFICATION_LABELS[r.verification_status]})
            </option>
          ))}
        </select>
        <span className="hint">
          Capture the page in Sources first. Re-read it whenever you change a
          date.
        </span>
      </label>
    </>
  );
}

function roundBody(form: FormData) {
  return {
    title: text(form, "title"),
    status: text(form, "status"),
    opens_on: text(form, "opens_on"),
    closes_on: text(form, "closes_on"),
    dates_note: text(form, "dates_note"),
    source_reference_id: text(form, "source_reference_id"),
  };
}

function Program({
  program,
  references,
  onChange,
}: {
  program: GrantProgramOut;
  references: SourceReferenceOut[];
  onChange: (p: GrantProgramOut) => void;
}) {
  const { busy, error, run } = useAction();
  const [editing, setEditing] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const amount = amountRange(
    program.min_amount_cents,
    program.max_amount_cents,
  );

  async function save(
    event: FormEvent<HTMLFormElement>,
    round?: GrantRoundOut,
  ) {
    event.preventDefault();
    const body = roundBody(new FormData(event.currentTarget));
    const updated = await run(() =>
      round
        ? apiRequest<GrantProgramOut>(
            "PATCH",
            `/admin/grant-rounds/${round.id}`,
            body,
          )
        : apiRequest<GrantProgramOut>(
            "POST",
            `/admin/grant-programs/${program.id}/rounds`,
            body,
          ),
    );
    if (updated) {
      onChange(updated);
      setEditing(null);
      setAdding(false);
    }
  }

  async function setStatus(status: "ACTIVE" | "RETIRED") {
    const updated = await run(() =>
      apiRequest<GrantProgramOut>(
        "PATCH",
        `/admin/grant-programs/${program.id}`,
        { status },
      ),
    );
    if (updated) onChange(updated);
  }

  return (
    <li className="finding">
      <div className="finding-head">
        <div>
          <h2 className="finding-title">{program.title}</h2>
          <p className="muted">
            {program.administrator.name} · {program.jurisdiction}
            {amount ? ` · ${amount}` : ""} · rules{" "}
            <code>{program.rule_set_key}</code>
          </p>
        </div>
        <span className="status">
          {program.status === "ACTIVE" ? "Matched" : "Retired"}
        </span>
      </div>
      <FormError message={error} />
      <ul className="task-list" aria-label={`Rounds of ${program.title}`}>
        {program.rounds.length === 0 ? (
          <li className="muted">
            No rounds yet. Customers see &ldquo;No round&rdquo;.
          </li>
        ) : null}
        {program.rounds.map((r) =>
          editing === r.id ? (
            <li key={r.id}>
              <form
                method="post"
                className="form"
                aria-label={`Update ${r.title}`}
                onSubmit={(e) => save(e, r)}
              >
                <RoundFields round={r} references={references} />
                <div className="actions">
                  <button type="submit" className="button" disabled={busy}>
                    Save round
                  </button>
                  <button
                    type="button"
                    className="link-button"
                    onClick={() => setEditing(null)}
                  >
                    Cancel
                  </button>
                </div>
              </form>
            </li>
          ) : (
            <li key={r.id} className="task">
              <span>
                <strong>{r.title}</strong>: {roundSummary(r)}
                {r.dates_note ? (
                  <span className="muted"> · {r.dates_note}</span>
                ) : null}
                <br />
                <span className="muted">
                  {r.source.citation} ·{" "}
                  {VERIFICATION_LABELS[r.source.verification_status]}
                </span>
                {r.check_source ? (
                  <span className="notice">
                    {" "}
                    The opening date has passed but the round is still marked
                    upcoming. Check the source.
                  </span>
                ) : null}
              </span>
              <button
                type="button"
                className="link-button"
                onClick={() => setEditing(r.id)}
              >
                Update
              </button>
            </li>
          ),
        )}
      </ul>
      {adding ? (
        <form
          method="post"
          className="form"
          aria-label={`Add a round to ${program.title}`}
          onSubmit={(e) => save(e)}
        >
          <RoundFields references={references} />
          <div className="actions">
            <button type="submit" className="button" disabled={busy}>
              Add round
            </button>
            <button
              type="button"
              className="link-button"
              onClick={() => setAdding(false)}
            >
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <div className="actions">
          <button
            type="button"
            className="button secondary"
            onClick={() => setAdding(true)}
          >
            Add a round
          </button>
          <button
            type="button"
            className="link-button"
            disabled={busy}
            onClick={() =>
              setStatus(program.status === "ACTIVE" ? "RETIRED" : "ACTIVE")
            }
          >
            {program.status === "ACTIVE"
              ? "Stop matching this program"
              : "Match this program again"}
          </button>
        </div>
      )}
    </li>
  );
}

/** Staff: keep each grant program's rounds and dates current, citing their sources. */
export function GrantsAdmin({
  initial,
  references,
}: {
  initial: GrantProgramOut[];
  references: SourceReferenceOut[];
}) {
  const [programs, setPrograms] = useState(initial);
  if (programs.length === 0) {
    return (
      <section className="panel empty">
        <p>
          No grant programs yet. Load the grant content pack (python -m app.cli
          rules load-pack grants_au_qld) to add the first ones.
        </p>
      </section>
    );
  }
  return (
    <ul className="finding-list" aria-label="Grant programs">
      {programs.map((p) => (
        <Program
          key={p.id}
          program={p}
          references={references}
          onChange={(updated) =>
            setPrograms((all) =>
              all.map((x) => (x.id === updated.id ? updated : x)),
            )
          }
        />
      ))}
    </ul>
  );
}
