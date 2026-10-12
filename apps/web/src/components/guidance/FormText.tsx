"use client";

import type { OfficialForm } from "@approvalready/shared-types";
import { createContext, useContext, type ReactNode } from "react";

import { formLabel, splitByForms } from "@/lib/officialForms";

const FormsContext = createContext<OfficialForm[]>([]);

/** Makes these forms linkable for every `FormText` inside (one product's forms). */
export function FormLinks({ forms, children }: { forms: OfficialForm[]; children: ReactNode }) {
  return <FormsContext.Provider value={forms}>{children}</FormsContext.Provider>;
}

/**
 * Text with every form it names linked to that form on the official site, e.g. "lodge a
 * Form 36" links "Form 36". Uses `forms` when given, otherwise the ones from `FormLinks`.
 */
export function FormText({ text, forms }: { text: string; forms?: OfficialForm[] }) {
  const inherited = useContext(FormsContext);
  const pieces = splitByForms(text, forms ?? inherited);
  return (
    <>
      {pieces.map((piece, i) =>
        typeof piece === "string" ? (
          piece
        ) : (
          <a
            key={i}
            href={piece.form.url}
            rel="noopener noreferrer"
            target="_blank"
            title={`${formLabel(piece.form)} (${piece.form.publisher})`}
          >
            {piece.text}
          </a>
        ),
      )}
    </>
  );
}

/** A list of forms, each linked, with who publishes it. */
export function FormList({
  forms,
  title = "Forms you'll need",
  level = 4,
}: {
  forms: OfficialForm[];
  title?: string;
  level?: 2 | 3 | 4;
}) {
  if (forms.length === 0) return null;
  const Heading = `h${level}` as const;
  return (
    <>
      <Heading className="subsection-title">{title}</Heading>
      <ul className="guide-list form-list">
        {forms.map((form) => (
          <li key={form.id}>
            <a href={form.url} rel="noopener noreferrer" target="_blank">
              {formLabel(form)}
            </a>
            <span className="muted">
              {" "}
              · {form.publisher}
              {form.note ? ` · ${form.note}` : ""}
            </span>
          </li>
        ))}
      </ul>
    </>
  );
}
