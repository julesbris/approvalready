"use client";

import type {
  AssessmentOut,
  DocumentOut,
  MemberOut,
  ProjectDetailOut,
  ProjectOut,
  ProjectStatus,
  PropertyOut,
  ReminderOut,
  TaskOut,
} from "@approvalready/shared-types";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { FormError } from "@/components/auth/FormStatus";
import { DocumentsPanel } from "@/components/documents/DocumentsPanel";
import { SitePanel } from "@/components/projects/SitePanel";
import { CONFIDENCE_LABELS } from "@/lib/assessment";
import { apiRequest } from "@/lib/client-api";
import {
  STATUS_ACTIONS,
  SUBMISSION_LABELS,
  formatDateTime,
  statusLabel,
  verticalName,
} from "@/lib/labels";
import { formatDate } from "@/lib/questionnaire";

type Props = {
  organisationId: string;
  project: ProjectDetailOut;
  tasks: TaskOut[];
  reminders: ReminderOut[];
  members: MemberOut[];
  properties?: PropertyOut[];
  documents?: DocumentOut[];
  currentUserId: string;
  canWrite: boolean;
};

/** Verticals whose projects are about a property (the API checks the same). */
const PROPERTY_VERTICALS = new Set(["PLANNING", "SELL", "RENT"]);

const RECURRENCE_LABELS: Record<string, string> = {
  WEEKLY: "Every week",
  MONTHLY: "Every month",
  YEARLY: "Every year",
};

export function ProjectWorkspace(props: Props) {
  const { organisationId, members, canWrite } = props;
  const router = useRouter();
  const [project, setProject] = useState(props.project);
  const [tasks, setTasks] = useState(props.tasks);
  const [reminders, setReminders] = useState(props.reminders);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const base = `/organisations/${organisationId}/projects/${project.id}`;
  const memberName = (userId: string | null | undefined) =>
    members.find((m) => m.user_id === userId)?.display_name ?? "Someone";

  /** Run one API call; returns the result on success, or null after showing the error. */
  async function run<T>(
    action: () => Promise<{ ok: true; data: T } | { ok: false; message: string }>,
  ): Promise<{ data: T } | null> {
    setBusy(true);
    setError(null);
    const result = await action();
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return null;
    }
    return { data: result.data };
  }

  async function changeStatus(status: ProjectStatus) {
    const updated = await run(() => apiRequest<ProjectOut>("POST", `${base}/status`, { status }));
    if (updated) setProject((p) => ({ ...p, ...updated.data }));
  }

  async function startQuestionnaire() {
    const started = await run(() => apiRequest("POST", `${base}/submissions`, {}));
    if (started) router.push(`/projects/${project.id}/questionnaire`);
  }

  async function runAssessment() {
    const assessment = await run(() => apiRequest<AssessmentOut>("POST", `${base}/assessments`));
    if (assessment) router.push(`/projects/${project.id}/assessments/${assessment.data.id}`);
  }

  async function addTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const task = await run(() =>
      apiRequest<TaskOut>("POST", `${base}/tasks`, {
        title: String(form.get("title") ?? "").trim(),
        due_on: String(form.get("due_on") ?? "") || null,
        assignee_user_id: String(form.get("assignee") ?? "") || null,
      }),
    );
    if (task) {
      setTasks((list) => [...list, task.data]);
      formElement.reset();
    }
  }

  async function toggleTask(task: TaskOut) {
    const updated = await run(() =>
      apiRequest<TaskOut>("PATCH", `${base}/tasks/${task.id}`, {
        status: task.status === "DONE" ? "OPEN" : "DONE",
      }),
    );
    if (updated) setTasks((list) => list.map((t) => (t.id === task.id ? updated.data : t)));
  }

  async function deleteTask(task: TaskOut) {
    const done = await run(() => apiRequest("DELETE", `${base}/tasks/${task.id}`));
    if (done) setTasks((list) => list.filter((t) => t.id !== task.id));
  }

  async function addReminder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const day = String(form.get("day") ?? "");
    const time = String(form.get("time") ?? "") || "09:00";
    if (!day) {
      setError("Choose a date for the reminder.");
      return;
    }
    const reminder = await run(() =>
      apiRequest<ReminderOut>("POST", `${base}/reminders`, {
        title: String(form.get("title") ?? "").trim(),
        // The browser's local time, sent with its offset.
        fires_at: new Date(`${day}T${time}`).toISOString(),
        recurrence: String(form.get("recurrence") ?? "") || null,
        recipient_user_id: String(form.get("recipient") ?? "") || null,
      }),
    );
    if (reminder) {
      setReminders((list) => [...list, reminder.data]);
      formElement.reset();
    }
  }

  async function cancelReminder(reminder: ReminderOut) {
    const done = await run(() => apiRequest("DELETE", `${base}/reminders/${reminder.id}`));
    if (done) {
      setReminders((list) =>
        list.map((r) => (r.id === reminder.id ? { ...r, status: "CANCELLED" } : r)),
      );
    }
  }

  const statusChanges = project.allowed_status_changes as ProjectStatus[];
  const submitted = project.submissions.some((s) => s.status === "SUBMITTED");
  const latest = project.latest_assessment;
  const scheduled = reminders.filter((r) => r.status === "SCHEDULED");

  return (
    <div className="workspace">
      <section className="page-head" aria-labelledby="project-title">
        <div>
          <h1 id="project-title" className="page-title">
            {project.title}
          </h1>
          <p className="muted">
            {verticalName(project.vertical)} · Reference {project.reference_code}
          </p>
          {project.description ? <p>{project.description}</p> : null}
        </div>
        <span className={`status status-${project.status.toLowerCase()}`}>
          {statusLabel(project.status)}
        </span>
      </section>

      <FormError message={error} />

      {canWrite && statusChanges.length > 0 ? (
        <div className="button-row tight" aria-label="Change status">
          {statusChanges.map((status) => (
            <button
              key={status}
              type="button"
              className="button button-secondary"
              disabled={busy}
              onClick={() => changeStatus(status)}
            >
              {STATUS_ACTIONS[status]}
            </button>
          ))}
        </div>
      ) : null}

      {PROPERTY_VERTICALS.has(project.vertical) && props.properties ? (
        <SitePanel
          organisationId={organisationId}
          project={project}
          properties={props.properties}
          canWrite={canWrite}
          onProjectChange={setProject}
        />
      ) : null}

      <section className="panel" aria-labelledby="questions-title">
        <h2 id="questions-title" className="section-title">
          Questionnaire
        </h2>
        <p className="muted">
          Your answers describe your situation. They are the facts an assessment will use, not an
          assessment themselves.
        </p>
        {project.submissions.length === 0 ? (
          canWrite ? (
            <button type="button" className="button" disabled={busy} onClick={startQuestionnaire}>
              Answer the questions
            </button>
          ) : (
            <p>No answers yet.</p>
          )
        ) : (
          <ul className="plain-list">
            {project.submissions.map((submission) => (
              <li key={submission.id}>
                <Link href={`/projects/${project.id}/questionnaire`}>
                  {submission.questionnaire_title}
                </Link>{" "}
                <span className="badge">
                  {SUBMISSION_LABELS[submission.status] ?? submission.status}
                </span>
                <div className="muted">
                  Version {submission.version} · Last saved {formatDateTime(submission.updated_at)}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="panel" aria-labelledby="assessment-title">
        <h2 id="assessment-title" className="section-title">
          Assessment
        </h2>
        {latest ? (
          <p>
            <Link href={`/projects/${project.id}/assessments/${latest.id}`}>
              Assessed {formatDate(latest.assessed_on)}
            </Link>
            : {CONFIDENCE_LABELS[latest.overall_confidence]} ·{" "}
            {latest.status === "NO_APPLICABLE_RULES"
              ? "no reviewed rules cover this yet"
              : `${latest.findings} finding${latest.findings === 1 ? "" : "s"}`}
          </p>
        ) : (
          <p className="muted">
            An assessment checks your submitted answers against the rules our team has sourced and
            reviewed, and shows how confident we are in each result.
          </p>
        )}
        {canWrite ? (
          <>
            <button
              type="button"
              className={latest ? "button button-secondary" : "button"}
              disabled={busy || !submitted || project.status === "ARCHIVED"}
              onClick={runAssessment}
            >
              {latest ? "Run a new assessment" : "Run assessment"}
            </button>
            {!submitted ? <p className="hint">Submit your answers first.</p> : null}
          </>
        ) : null}
      </section>

      {props.documents ? (
        <DocumentsPanel
          organisationId={organisationId}
          projectId={project.id}
          documents={props.documents}
          canWrite={canWrite}
        />
      ) : null}

      <section className="panel" aria-labelledby="tasks-title">
        <h2 id="tasks-title" className="section-title">
          Tasks
        </h2>
        {tasks.length === 0 ? <p className="muted">No tasks yet.</p> : null}
        <ul className="task-list">
          {tasks.map((task) => (
            <li key={task.id} className={task.status === "DONE" ? "task done" : "task"}>
              <label>
                <input
                  type="checkbox"
                  checked={task.status === "DONE"}
                  disabled={!canWrite || busy}
                  onChange={() => toggleTask(task)}
                />
                <span>{task.title}</span>
              </label>
              <span className="muted">
                {task.source === "RULE" ? "From your assessment" : null}
                {task.source === "RULE" && (task.due_on || task.assignee_user_id) ? " · " : null}
                {task.due_on ? `Due ${formatDate(task.due_on)}` : null}
                {task.due_on && task.assignee_user_id ? " · " : null}
                {task.assignee_user_id ? memberName(task.assignee_user_id) : null}
              </span>
              {canWrite ? (
                <button
                  type="button"
                  className="button-link"
                  disabled={busy}
                  onClick={() => deleteTask(task)}
                  aria-label={`Delete task ${task.title}`}
                >
                  Delete
                </button>
              ) : null}
            </li>
          ))}
        </ul>
        {canWrite ? (
          <form className="form inline-form" onSubmit={addTask} aria-label="Add a task">
            <label>
              Task
              <input name="title" required maxLength={200} />
            </label>
            <label>
              Due (optional)
              <input name="due_on" type="date" />
            </label>
            {members.length > 1 ? (
              <label>
                For
                <select name="assignee" defaultValue="">
                  <option value="">Nobody in particular</option>
                  {members.map((m) => (
                    <option key={m.user_id} value={m.user_id}>
                      {m.display_name}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            <button type="submit" className="button button-secondary" disabled={busy}>
              Add task
            </button>
          </form>
        ) : null}
      </section>

      <section className="panel" aria-labelledby="reminders-title">
        <h2 id="reminders-title" className="section-title">
          Reminders
        </h2>
        <p className="notice">
          Reminders are saved now. Sending them by email is switched on in a later update, so
          don&apos;t rely on them for deadlines yet.
        </p>
        {scheduled.length === 0 ? <p className="muted">No reminders scheduled.</p> : null}
        <ul className="task-list">
          {scheduled.map((reminder) => (
            <li key={reminder.id} className="task">
              <span>{reminder.title}</span>
              <span className="muted">
                {formatDateTime(reminder.fires_at)}
                {reminder.recurrence ? ` · ${RECURRENCE_LABELS[reminder.recurrence] ?? ""}` : ""}
                {reminder.recipient_user_id !== props.currentUserId
                  ? ` · for ${memberName(reminder.recipient_user_id)}`
                  : ""}
              </span>
              {canWrite ? (
                <button
                  type="button"
                  className="button-link"
                  disabled={busy}
                  onClick={() => cancelReminder(reminder)}
                  aria-label={`Cancel reminder ${reminder.title}`}
                >
                  Cancel
                </button>
              ) : null}
            </li>
          ))}
        </ul>
        {canWrite ? (
          <form className="form inline-form" onSubmit={addReminder} aria-label="Add a reminder">
            <label>
              Remind me to
              <input name="title" required maxLength={200} />
            </label>
            <label>
              On
              <input name="day" type="date" required />
            </label>
            <label>
              At
              <input name="time" type="time" defaultValue="09:00" />
            </label>
            <label>
              Repeat
              <select name="recurrence" defaultValue="">
                <option value="">Once</option>
                {Object.entries(RECURRENCE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            {members.length > 1 ? (
              <label>
                Who
                <select name="recipient" defaultValue="">
                  <option value="">Me</option>
                  {members
                    .filter((m) => m.user_id !== props.currentUserId)
                    .map((m) => (
                      <option key={m.user_id} value={m.user_id}>
                        {m.display_name}
                      </option>
                    ))}
                </select>
              </label>
            ) : null}
            <button type="submit" className="button button-secondary" disabled={busy}>
              Add reminder
            </button>
          </form>
        ) : null}
      </section>
    </div>
  );
}
