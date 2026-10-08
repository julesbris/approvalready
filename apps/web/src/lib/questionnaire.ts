/**
 * Questionnaire helpers for the guided form: which questions are showing for the current
 * (possibly unsaved) answers, and converting what people type into API answer values.
 *
 * Mirrors `evaluate_answers` and `to_facts` in apps/api/app/modules/questionnaires/engine.py.
 * The API repeats this on every save and its result replaces the browser's.
 */

import type { QuestionOut, QuestionnaireOut } from "@approvalready/shared-types";

import { type Condition, type Facts, evaluate } from "@/lib/conditions";

export type Answers = Record<string, unknown>;

type FieldDef = { key: string; label: string; type: string; required?: boolean };

export function questionFields(question: QuestionOut): FieldDef[] {
  const fields = (question.validation as { fields?: FieldDef[] }).fields;
  return Array.isArray(fields) ? fields : [];
}

export function allQuestions(questionnaire: QuestionnaireOut): QuestionOut[] {
  return questionnaire.sections.flatMap((section) => section.questions);
}

function decimal(value: unknown): unknown {
  return typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value))
    ? Number(value)
    : value;
}

/** Facts one answer provides. Structured answers also expose `key.field` facts. */
export function toFacts(question: QuestionOut, value: unknown): Facts {
  if (value === undefined || value === null) return {};
  if (question.type === "DECIMAL") return { [question.key]: decimal(value) };
  if ((question.type === "ADDRESS" || question.type === "OBJECT") && isRecord(value)) {
    const facts: Facts = { [question.key]: value };
    const decimals = new Set(questionFields(question).filter((f) => f.type === "DECIMAL").map((f) => f.key));
    for (const [name, field] of Object.entries(value)) {
      facts[`${question.key}.${name}`] = decimals.has(name) ? decimal(field) : field;
    }
    return facts;
  }
  return { [question.key]: value };
}

export type Visibility = { visible: Set<string>; missingRequired: string[] };

export function isAnswered(value: unknown): boolean {
  if (value === undefined || value === null) return false;
  if (typeof value === "string") return value.trim() !== "";
  if (Array.isArray(value)) return value.length > 0;
  if (isRecord(value)) return Object.values(value).some(isAnswered);
  return true;
}

/** Walk questions in order; a question only sees facts from earlier visible answers. */
export function visibility(questionnaire: QuestionnaireOut, answers: Answers): Visibility {
  const facts: Facts = {};
  const visible = new Set<string>();
  const missingRequired: string[] = [];
  for (const question of allQuestions(questionnaire)) {
    const condition = question.visible_when as Condition | null;
    if (condition && evaluate(condition, facts) !== "TRUE") continue;
    visible.add(question.key);
    const value = answers[question.key];
    if (isAnswered(value)) Object.assign(facts, toFacts(question, value));
    else if (question.required) missingRequired.push(question.key);
  }
  return { visible, missingRequired };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

// --- Typed input -------------------------------------------------------------------------

export type Parsed = { value: unknown } | { error: string };

/** Whole number from a text box. Empty clears the answer. */
export function parseWholeNumber(text: string): Parsed {
  const trimmed = text.trim().replace(/,/g, "");
  if (trimmed === "") return { value: null };
  if (!/^-?\d{1,15}$/.test(trimmed)) return { error: "Enter a whole number." };
  return { value: Number(trimmed) };
}

/** Exact decimal, kept as a string (the API stores decimals exactly). */
export function parseDecimal(text: string): Parsed {
  const trimmed = text.trim().replace(/,/g, "");
  if (trimmed === "") return { value: null };
  if (!/^-?\d{1,15}(\.\d+)?$/.test(trimmed)) return { error: "Enter a number." };
  return { value: trimmed };
}

/** Dollars typed by a person, as whole cents for the API. */
export function parseDollars(text: string): Parsed {
  const trimmed = text.trim().replace(/[$,\s]/g, "");
  if (trimmed === "") return { value: null };
  const match = /^(\d{1,13})(?:\.(\d{1,2}))?$/.exec(trimmed);
  if (!match) return { error: "Enter an amount in dollars, for example 1500 or 1500.50." };
  const cents = (match[2] ?? "").padEnd(2, "0");
  return { value: Number(match[1]) * 100 + Number(cents) };
}

export function formatDollars(cents: unknown): string {
  if (typeof cents !== "number" || !Number.isInteger(cents)) return "";
  const whole = Math.trunc(cents / 100);
  const part = Math.abs(cents % 100);
  return part === 0 ? String(whole) : `${whole}.${String(part).padStart(2, "0")}`;
}

/** Human-readable answer for the review step. */
export function displayAnswer(question: QuestionOut, value: unknown): string {
  if (!isAnswered(value)) return "Not answered";
  const label = (v: unknown) => question.options.find((o) => o.value === v)?.label ?? String(v);
  switch (question.type) {
    case "BOOLEAN":
      return value === true ? "Yes" : "No";
    case "SELECT":
      return label(value);
    case "MULTISELECT":
      return Array.isArray(value) ? value.map(label).join(", ") : String(value);
    case "CURRENCY":
      return typeof value === "number"
        ? new Intl.NumberFormat("en-AU", { style: "currency", currency: "AUD" }).format(value / 100)
        : String(value);
    case "DATE":
      return typeof value === "string" ? formatDate(value) : String(value);
    case "ADDRESS": {
      const a = value as Record<string, string>;
      return [a.line1, a.line2, [a.suburb, a.state, a.postcode].filter(Boolean).join(" ")]
        .filter(Boolean)
        .join(", ");
    }
    case "OBJECT":
      return questionFields(question)
        .filter((f) => isAnswered((value as Record<string, unknown>)[f.key]))
        .map((f) => {
          const v = (value as Record<string, unknown>)[f.key];
          return `${f.label}: ${typeof v === "boolean" ? (v ? "Yes" : "No") : String(v)}`;
        })
        .join("; ");
    default:
      return String(value);
  }
}

export function formatDate(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!match) return iso;
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  return new Intl.DateTimeFormat("en-AU", { dateStyle: "medium", timeZone: "UTC" }).format(date);
}

/** Initial text for number-like questions from a stored answer. */
export function textFor(question: QuestionOut, value: unknown): string | undefined {
  if (value === undefined || value === null) {
    return ["NUMBER", "DECIMAL", "CURRENCY"].includes(question.type) ? "" : undefined;
  }
  if (question.type === "NUMBER" || question.type === "DECIMAL") return String(value);
  if (question.type === "CURRENCY") return formatDollars(value);
  return undefined;
}

/** Parse number-like text for a question; other types have no text. */
export function parseText(question: QuestionOut, text: string): Parsed {
  if (question.type === "NUMBER") return parseWholeNumber(text);
  if (question.type === "DECIMAL") return parseDecimal(text);
  if (question.type === "CURRENCY") return parseDollars(text);
  return { value: text };
}

/** The value to send for an answer: blanks become null (which clears the answer). */
export function cleanAnswer(question: QuestionOut, value: unknown): unknown {
  if (value === undefined || value === null) return null;
  if (typeof value === "string") return value.trim() === "" ? null : value;
  if (Array.isArray(value)) return value.length === 0 ? null : value;
  if (isRecord(value)) {
    const entries = Object.entries(value).filter(
      ([, v]) => v !== null && v !== undefined && !(typeof v === "string" && v.trim() === ""),
    );
    return entries.length === 0 ? null : Object.fromEntries(entries);
  }
  return value;
}
