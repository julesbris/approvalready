import type { OfficialForm } from "@approvalready/shared-types";

export type FormPiece = string | { text: string; form: OfficialForm };

function escape(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** The words in our text that refer to a form: its mentions, or else its number. */
export function formPhrases(form: OfficialForm): string[] {
  if (form.mentions.length > 0) return form.mentions;
  return form.code ? [form.code] : [];
}

/**
 * Text split into plain runs and mentions of the given forms, so each mention can link to
 * its form. "Form 1" never matches inside "Form 1a" or "Form 18"; the longest phrase wins
 * where two could match at the same place.
 */
export function splitByForms(text: string, forms: OfficialForm[]): FormPiece[] {
  const byPhrase = new Map<string, OfficialForm>();
  for (const form of forms) {
    for (const phrase of formPhrases(form)) {
      if (!byPhrase.has(phrase)) byPhrase.set(phrase, form);
    }
  }
  if (byPhrase.size === 0 || !text) return [text];
  const phrases = [...byPhrase.keys()].sort((a, b) => b.length - a.length);
  const pattern = new RegExp(`(?<![\\w])(${phrases.map(escape).join("|")})(?![\\w])`, "g");
  const pieces: FormPiece[] = [];
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    const at = match.index ?? 0;
    if (at > last) pieces.push(text.slice(last, at));
    pieces.push({ text: match[0], form: byPhrase.get(match[0])! });
    last = at + match[0].length;
  }
  if (last < text.length) pieces.push(text.slice(last));
  return pieces;
}

/** How a form is named in a list: its number and name. */
export function formLabel(form: OfficialForm): string {
  if (form.code && !form.name.toLowerCase().includes(form.code.toLowerCase())) {
    return `${form.code} ${form.name}`;
  }
  return form.name;
}

/** The forms these texts mention, each once, in the order they first appear. */
export function formsMentioned(
  texts: (string | null | undefined)[],
  forms: OfficialForm[],
): OfficialForm[] {
  const found: OfficialForm[] = [];
  for (const text of texts) {
    if (!text) continue;
    for (const piece of splitByForms(text, forms)) {
      if (typeof piece !== "string" && !found.includes(piece.form)) found.push(piece.form);
    }
  }
  return found;
}
