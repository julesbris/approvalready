"use client";

import type { RuleOut, RuleSetOut } from "@approvalready/shared-types";
import { VERTICALS } from "@approvalready/shared-types";
import { useRouter } from "next/navigation";
import type { FormEvent } from "react";

import { CONDITION_HELP, parseJson, prettyJson } from "@/components/admin/json";
import { useAction } from "@/components/admin/useAction";
import { FormError } from "@/components/auth/FormStatus";
import { defaultBrand } from "@/lib/brand";
import { apiRequest } from "@/lib/client-api";

export function verticalName(vertical: string): string {
  return defaultBrand.products.find((p) => p.key === vertical)?.name ?? vertical;
}

function text(form: FormData, name: string): string | null {
  const value = String(form.get(name) ?? "").trim();
  return value === "" ? null : value;
}

/** Create a rule set (a group of rules for one vertical and jurisdiction). */
export function NewRuleSetForm() {
  const router = useRouter();
  const action = useAction();

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const scope = parseJson(String(form.get("applies_when") ?? ""), "scope", {
      optional: true,
    });
    if (!scope.ok) return action.setError(scope.message);
    const created = await action.run(() =>
      apiRequest<RuleSetOut>("POST", "/admin/rule-sets", {
        key: text(form, "key"),
        vertical: text(form, "vertical"),
        jurisdiction: text(form, "jurisdiction"),
        title: text(form, "title"),
        description: text(form, "description"),
        applies_when: scope.value,
      }),
    );
    if (created) router.push(`/admin/rules/${created.id}`);
  }

  return (
    <form className="form" onSubmit={submit} aria-label="Add a rule set">
      <FormError message={action.error} />
      <label>
        Title
        <input name="title" required maxLength={300} />
      </label>
      <label>
        Key
        <input name="key" required maxLength={100} placeholder="e.g. qld-secondary-dwellings" />
        <span className="hint">
          Lower-case letters, numbers, dots and dashes. Cannot change later.
        </span>
      </label>
      <label>
        Product
        <select name="vertical" required defaultValue="">
          <option value="" disabled>
            Choose…
          </option>
          {VERTICALS.map((v) => (
            <option key={v} value={v}>
              {verticalName(v)}
            </option>
          ))}
        </select>
      </label>
      <label>
        Jurisdiction
        <input name="jurisdiction" required placeholder="QLD or LGA:QLD_CAIRNS" />
      </label>
      <label>
        Description (optional)
        <textarea name="description" rows={2} maxLength={2000} />
      </label>
      <label>
        Applies when (optional condition)
        <textarea name="applies_when" rows={4} className="code-input" />
        <span className="hint">
          Leave empty if the rules apply to every project in this product. {CONDITION_HELP}
        </span>
      </label>
      <button type="submit" className="button" disabled={action.busy}>
        Add rule set
      </button>
    </form>
  );
}

/** Edit a rule set's title, description and scope. */
export function RuleSetScopeForm({ ruleSet }: { ruleSet: RuleSetOut }) {
  const router = useRouter();
  const action = useAction();

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const scope = parseJson(String(form.get("applies_when") ?? ""), "scope", {
      optional: true,
    });
    if (!scope.ok) return action.setError(scope.message);
    const saved = await action.run(() =>
      apiRequest<RuleSetOut>("PATCH", `/admin/rule-sets/${ruleSet.id}`, {
        title: text(form, "title"),
        jurisdiction: text(form, "jurisdiction"),
        description: text(form, "description"),
        applies_when: scope.value,
      }),
    );
    if (saved) router.refresh();
  }

  return (
    <form className="form" onSubmit={submit} aria-label="Edit rule set">
      <FormError message={action.error} />
      <label>
        Title
        <input name="title" required maxLength={300} defaultValue={ruleSet.title} />
      </label>
      <label>
        Jurisdiction
        <input name="jurisdiction" required defaultValue={ruleSet.jurisdiction} />
      </label>
      <label>
        Description (optional)
        <textarea name="description" rows={2} defaultValue={ruleSet.description ?? ""} />
      </label>
      <label>
        Applies when (optional condition)
        <textarea
          name="applies_when"
          rows={5}
          className="code-input"
          defaultValue={prettyJson(ruleSet.applies_when)}
        />
        <span className="hint">
          Projects outside this scope skip every rule in the set. A scope that can&apos;t be checked
          yet asks the customer for the missing answers.
        </span>
      </label>
      <button type="submit" className="button button-secondary" disabled={action.busy}>
        Save rule set
      </button>
    </form>
  );
}

/** Add a rule; it starts as draft version 1, opened in the editor. */
export function NewRuleForm({ ruleSetId }: { ruleSetId: string }) {
  const router = useRouter();
  const action = useAction();

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const condition = parseJson(String(form.get("condition") ?? ""), "condition");
    if (!condition.ok) return action.setError(condition.message);
    const created = await action.run(() =>
      apiRequest<RuleOut>("POST", `/admin/rule-sets/${ruleSetId}/rules`, {
        key: text(form, "key"),
        title: text(form, "title"),
        condition: condition.value,
      }),
    );
    if (created && created.versions[0]) {
      router.push(`/admin/rules/versions/${created.versions[0].id}`);
    }
  }

  return (
    <form className="form" onSubmit={submit} aria-label="Add a rule">
      <FormError message={action.error} />
      <label>
        Title
        <input name="title" required maxLength={300} />
      </label>
      <label>
        Key
        <input name="key" required maxLength={100} placeholder="e.g. floor-area-limit" />
      </label>
      <label>
        Condition
        <textarea name="condition" required rows={5} className="code-input" />
        <span className="hint">{CONDITION_HELP}</span>
      </label>
      <button type="submit" className="button" disabled={action.busy}>
        Add rule and open draft
      </button>
    </form>
  );
}
