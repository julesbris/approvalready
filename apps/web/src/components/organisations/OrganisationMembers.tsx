"use client";

import type { InvitationOut, MemberOut } from "@approvalready/shared-types";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";
import { ASSIGNABLE_ROLES, ROLE_HELP, ROLE_LABELS, formatDateTime, roleList } from "@/lib/labels";

type Props = {
  organisationId: string;
  kind: string;
  currentUserId: string;
  members: MemberOut[];
  invitations: InvitationOut[];
  canManageMembers: boolean;
  canInvite: boolean;
};

function RoleChoices({
  kind,
  name,
  selected,
  onChange,
}: {
  kind: string;
  name: string;
  selected: string[];
  onChange?: (roles: string[]) => void;
}) {
  return (
    <div className="options">
      {(ASSIGNABLE_ROLES[kind] ?? []).map((role) => (
        <label key={role} className="option">
          <input
            type="checkbox"
            name={name}
            value={role}
            {...(onChange
              ? {
                  checked: selected.includes(role),
                  onChange: (e) =>
                    onChange(
                      e.target.checked ? [...selected, role] : selected.filter((r) => r !== role),
                    ),
                }
              : { defaultChecked: selected.includes(role) })}
          />
          <span>
            {ROLE_LABELS[role] ?? role}
            {ROLE_HELP[role] ? <span className="muted"> {ROLE_HELP[role]}</span> : null}
          </span>
        </label>
      ))}
    </div>
  );
}

export function OrganisationMembers(props: Props) {
  const { organisationId, kind, currentUserId, canManageMembers, canInvite } = props;
  const router = useRouter();
  const [members, setMembers] = useState(props.members);
  const [invitations, setInvitations] = useState(props.invitations);
  const [editing, setEditing] = useState<{ id: string; roles: string[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const base = `/organisations/${organisationId}`;

  async function call<T>(method: "POST" | "PUT" | "DELETE", path: string, body?: unknown) {
    setBusy(true);
    setError(null);
    setNotice(null);
    const result = await apiRequest<T>(method, path, body);
    setBusy(false);
    if (!result.ok) setError(result.message);
    return result.ok ? { data: result.data } : null;
  }

  async function saveRoles() {
    if (!editing) return;
    const saved = await call<MemberOut>("PUT", `${base}/members/${editing.id}/roles`, {
      roles: editing.roles,
    });
    if (saved) {
      setMembers((list) => list.map((m) => (m.id === editing.id ? saved.data : m)));
      setEditing(null);
    }
  }

  async function remove(member: MemberOut) {
    const self = member.user_id === currentUserId;
    const question = self
      ? "Leave this organisation? You will lose access to its projects."
      : `Remove ${member.display_name} from this organisation?`;
    if (!window.confirm(question)) return;
    if (await call("DELETE", `${base}/members/${member.id}`)) {
      if (self) {
        router.push("/account");
        router.refresh();
        return;
      }
      setMembers((list) => list.filter((m) => m.id !== member.id));
    }
  }

  async function invite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const roles = form.getAll("roles").map(String);
    if (roles.length === 0) {
      setError("Choose at least one role for the person you're inviting.");
      return;
    }
    const created = await call<InvitationOut>("POST", `${base}/invitations`, {
      email: String(form.get("email") ?? "").trim(),
      roles,
    });
    if (created) {
      setInvitations((list) => [created.data, ...list]);
      setNotice(`Invitation sent to ${created.data.email}.`);
      formElement.reset();
    }
  }

  async function revoke(invitation: InvitationOut) {
    if (await call("DELETE", `${base}/invitations/${invitation.id}`)) {
      setInvitations((list) => list.filter((i) => i.id !== invitation.id));
    }
  }

  return (
    <>
      <FormError message={error} />
      {notice ? (
        <p className="form-notice" role="status">
          {notice}
        </p>
      ) : null}

      <section className="panel" aria-labelledby="members-title">
        <h2 id="members-title" className="section-title">
          Members
        </h2>
        <ul className="org-list" aria-label="Members">
          {members.map((member) => (
            <li key={member.id} className="org-item">
              <div>
                <strong>{member.display_name}</strong>
                {member.user_id === currentUserId ? <span className="badge">You</span> : null}
              </div>
              <div className="muted">
                {member.email} · {roleList(member.roles)}
              </div>
              {editing?.id === member.id ? (
                <fieldset className="role-editor" disabled={busy}>
                  <legend>Roles for {member.display_name}</legend>
                  <RoleChoices
                    kind={kind}
                    name={`roles-${member.id}`}
                    selected={editing.roles}
                    onChange={(roles) => setEditing({ id: member.id, roles })}
                  />
                  <div className="button-row tight">
                    <button type="button" className="button" onClick={saveRoles}>
                      Save roles
                    </button>
                    <button
                      type="button"
                      className="button button-secondary"
                      onClick={() => setEditing(null)}
                    >
                      Cancel
                    </button>
                  </div>
                </fieldset>
              ) : (
                <div className="org-actions">
                  {canManageMembers ? (
                    <button
                      type="button"
                      className="button-link"
                      disabled={busy}
                      onClick={() => setEditing({ id: member.id, roles: [...member.roles] })}
                    >
                      Change roles
                    </button>
                  ) : null}
                  {canManageMembers || member.user_id === currentUserId ? (
                    <button
                      type="button"
                      className="button-link"
                      disabled={busy}
                      onClick={() => remove(member)}
                    >
                      {member.user_id === currentUserId ? "Leave organisation" : "Remove"}
                    </button>
                  ) : null}
                </div>
              )}
            </li>
          ))}
        </ul>
      </section>

      {canInvite ? (
        <section className="panel" aria-labelledby="invite-title">
          <h2 id="invite-title" className="section-title">
            Invite someone
          </h2>
          <form className="form" onSubmit={invite}>
            <label>
              Email
              <input name="email" type="email" required autoComplete="off" />
            </label>
            <fieldset>
              <legend>Roles</legend>
              <RoleChoices kind={kind} name="roles" selected={kind === "PROFESSIONAL_PRACTICE" ? [] : ["CUSTOMER"]} />
            </fieldset>
            <div>
              <button type="submit" className="button" disabled={busy}>
                Send invitation
              </button>
            </div>
          </form>
          {invitations.length > 0 ? (
            <>
              <h3 className="subsection-title">Waiting to be accepted</h3>
              <ul className="org-list" aria-label="Open invitations">
                {invitations.map((invitation) => (
                  <li key={invitation.id} className="org-item">
                    <div>
                      <strong>{invitation.email}</strong>
                    </div>
                    <div className="muted">
                      {roleList(invitation.roles)} · Expires {formatDateTime(invitation.expires_at)}
                    </div>
                    <div className="org-actions">
                      <button
                        type="button"
                        className="button-link"
                        disabled={busy}
                        onClick={() => revoke(invitation)}
                      >
                        Cancel invitation
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </section>
      ) : null}
    </>
  );
}
