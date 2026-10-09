"use client";

import type { QuestionOut } from "@approvalready/shared-types";
import type { ReactNode } from "react";

import { type FileContext, FileAnswer } from "@/components/questionnaire/FileAnswer";
import { questionFields } from "@/lib/questionnaire";

export const AU_STATES = [
  ["QLD", "Queensland"],
  ["NSW", "New South Wales"],
  ["VIC", "Victoria"],
  ["TAS", "Tasmania"],
  ["SA", "South Australia"],
  ["WA", "Western Australia"],
  ["NT", "Northern Territory"],
  ["ACT", "Australian Capital Territory"],
] as const;

type Props = {
  question: QuestionOut;
  value: unknown;
  /** Raw text for number-like questions, so half-typed input isn't lost. */
  text: string | undefined;
  error: string | undefined;
  disabled: boolean;
  onValue: (value: unknown) => void;
  onText: (text: string) => void;
  /** Where FILE answers upload to. Without it a FILE question is shown read-only. */
  files?: FileContext;
};

/** One question, rendered for its type, with its label, help text and error. */
export function QuestionField(props: Props) {
  const { question, value, text, error, disabled, onValue, onText, files } = props;
  const id = `q-${question.key.replace(/[^a-z0-9_-]/gi, "-")}`;
  const helpId = question.help_text ? `${id}-help` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [helpId, errorId].filter(Boolean).join(" ") || undefined;
  const common = {
    id,
    disabled,
    "aria-describedby": describedBy,
    "aria-invalid": error ? true : undefined,
    "aria-required": question.required || undefined,
  } as const;
  const label = (
    <>
      {question.label}
      {question.required ? null : <span className="optional"> (optional)</span>}
    </>
  );
  const help = question.help_text ? (
    <p id={helpId} className="hint">
      {question.help_text}
    </p>
  ) : null;
  const errorText = error ? (
    <p id={errorId} className="field-error">
      {error}
    </p>
  ) : null;

  const asText = (v: unknown) => (typeof v === "string" ? v : "");

  function single(input: ReactNode) {
    return (
      <div className={error ? "question has-error" : "question"}>
        <label htmlFor={id}>{label}</label>
        {help}
        {input}
        {errorText}
      </div>
    );
  }

  function group(children: ReactNode) {
    return (
      <fieldset
        className={error ? "question has-error" : "question"}
        aria-describedby={describedBy}
        disabled={disabled}
      >
        <legend>{label}</legend>
        {help}
        {children}
        {errorText}
      </fieldset>
    );
  }

  switch (question.type) {
    case "TEXT":
      return single(
        <input {...common} value={asText(value)} onChange={(e) => onValue(e.target.value)} />,
      );
    case "TEXTAREA":
      return single(
        <textarea
          {...common}
          rows={4}
          value={asText(value)}
          onChange={(e) => onValue(e.target.value)}
        />,
      );
    case "NUMBER":
    case "DECIMAL":
      return single(
        <input
          {...common}
          inputMode={question.type === "NUMBER" ? "numeric" : "decimal"}
          className="input-short"
          value={text ?? ""}
          onChange={(e) => onText(e.target.value)}
        />,
      );
    case "CURRENCY":
      return single(
        <span className="input-prefix">
          <span aria-hidden="true">$</span>
          <input
            {...common}
            inputMode="decimal"
            className="input-short"
            value={text ?? ""}
            onChange={(e) => onText(e.target.value)}
          />
        </span>,
      );
    case "DATE":
      return single(
        <input
          {...common}
          type="date"
          className="input-short"
          value={asText(value)}
          onChange={(e) => onValue(e.target.value)}
        />,
      );
    case "BOOLEAN":
      return group(
        <div className="options options-inline">
          {[
            [true, "Yes"],
            [false, "No"],
          ].map(([optionValue, optionLabel]) => (
            <label key={String(optionValue)} className="option">
              <input
                type="radio"
                name={id}
                checked={value === optionValue}
                onChange={() => onValue(optionValue)}
              />
              {optionLabel}
            </label>
          ))}
        </div>,
      );
    case "SELECT":
      if (question.options.length > 8) {
        return single(
          <select {...common} value={asText(value)} onChange={(e) => onValue(e.target.value || null)}>
            <option value="">Choose…</option>
            {question.options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>,
        );
      }
      return group(
        <div className="options">
          {question.options.map((o) => (
            <label key={o.value} className="option">
              <input
                type="radio"
                name={id}
                checked={value === o.value}
                onChange={() => onValue(o.value)}
              />
              {o.label}
            </label>
          ))}
        </div>,
      );
    case "MULTISELECT": {
      const chosen = Array.isArray(value) ? (value as string[]) : [];
      return group(
        <div className="options">
          {question.options.map((o) => (
            <label key={o.value} className="option">
              <input
                type="checkbox"
                checked={chosen.includes(o.value)}
                onChange={(e) =>
                  onValue(
                    e.target.checked ? [...chosen, o.value] : chosen.filter((v) => v !== o.value),
                  )
                }
              />
              {o.label}
            </label>
          ))}
        </div>,
      );
    }
    case "ADDRESS": {
      const address = (value && typeof value === "object" ? value : {}) as Record<string, string>;
      const set = (field: string, fieldValue: string) => onValue({ ...address, [field]: fieldValue });
      return group(
        <div className="address-fields">
          <label>
            Street address
            <input
              autoComplete="address-line1"
              value={address.line1 ?? ""}
              onChange={(e) => set("line1", e.target.value)}
            />
          </label>
          <label>
            Address line 2 <span className="optional">(optional)</span>
            <input
              autoComplete="address-line2"
              value={address.line2 ?? ""}
              onChange={(e) => set("line2", e.target.value)}
            />
          </label>
          <div className="address-row">
            <label>
              Suburb or town
              <input
                autoComplete="address-level2"
                value={address.suburb ?? ""}
                onChange={(e) => set("suburb", e.target.value)}
              />
            </label>
            <label>
              State
              <select value={address.state ?? ""} onChange={(e) => set("state", e.target.value)}>
                <option value="">Choose…</option>
                {AU_STATES.map(([code, name]) => (
                  <option key={code} value={code}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Postcode
              <input
                className="input-short"
                inputMode="numeric"
                autoComplete="postal-code"
                maxLength={4}
                value={address.postcode ?? ""}
                onChange={(e) => set("postcode", e.target.value)}
              />
            </label>
          </div>
        </div>,
      );
    }
    case "OBJECT": {
      const record = (value && typeof value === "object" ? value : {}) as Record<string, unknown>;
      const set = (field: string, fieldValue: unknown) => onValue({ ...record, [field]: fieldValue });
      return group(
        <div className="address-fields">
          {questionFields(question).map((field) => (
            <label key={field.key}>
              {field.label}
              {field.required ? null : <span className="optional"> (optional)</span>}
              {field.type === "BOOLEAN" ? (
                <select
                  value={record[field.key] === undefined ? "" : String(record[field.key])}
                  onChange={(e) =>
                    set(field.key, e.target.value === "" ? null : e.target.value === "true")
                  }
                >
                  <option value="">Choose…</option>
                  <option value="true">Yes</option>
                  <option value="false">No</option>
                </select>
              ) : (
                <input
                  type={field.type === "DATE" ? "date" : "text"}
                  inputMode={
                    field.type === "NUMBER" ? "numeric" : field.type === "DECIMAL" ? "decimal" : undefined
                  }
                  value={typeof record[field.key] === "string" || typeof record[field.key] === "number" ? String(record[field.key]) : ""}
                  onChange={(e) => set(field.key, e.target.value)}
                />
              )}
            </label>
          ))}
        </div>,
      );
    }
    case "FILE": {
      const maxFiles = Number((question.validation as { max_files?: number }).max_files ?? 5);
      if (!files) {
        const count = Array.isArray(value) ? value.length : 0;
        return group(<p className="muted">{count ? `${count} file(s) attached` : "No files"}</p>);
      }
      return group(
        <FileAnswer
          {...files}
          id={id}
          value={value}
          maxFiles={maxFiles}
          disabled={disabled}
          describedBy={describedBy}
          onValue={onValue}
        />,
      );
    }
    default:
      return group(<p className="muted">This question can&apos;t be shown yet.</p>);
  }
}
