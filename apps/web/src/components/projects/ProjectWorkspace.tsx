"use client";

import type {
  BusinessProfileOut,
  ChecklistDefinitionOut,
  ChecklistOut,
  CouncilOut,
  DocumentOut,
  MemberOut,
  ProjectDetailOut,
  ProjectOut,
  ProjectStatus,
  PropertyOut,
  ReminderOut,
  TaskOut,
  VesselOut,
  ProjectPlanOut,
  WhatsLeftOut,
} from "@approvalready/shared-types";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { FormError } from "@/components/auth/FormStatus";
import { CouncilGuide } from "@/components/councils/CouncilGuide";
import { DocumentsPanel } from "@/components/documents/DocumentsPanel";
import { BusinessPanel } from "@/components/projects/BusinessPanel";
import { ChecklistsPanel } from "@/components/projects/ChecklistsPanel";
import { SitePanel } from "@/components/projects/SitePanel";
import { VesselPanel } from "@/components/projects/VesselPanel";
import { WhatsLeft } from "@/components/projects/WhatsLeft";
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
  businesses?: BusinessProfileOut[];
  vessels?: VesselOut[];
  checklists?: ChecklistOut[];
  checklistDefinitions?: ChecklistDefinitionOut[];
  documents?: DocumentOut[];
  /** For a planning project in a council we know: how to apply to it. */
  council?: CouncilOut;
  whatsLeft?: WhatsLeftOut;
  /** The project plan's state (undefined when it couldn't be read). */
  plan?: ProjectPlanOut;
  currentUserId: string;
  canWrite: boolean;
};

/** Verticals whose projects are about a property (the API checks the same). */
const PROPERTY_VERTICALS = new Set(["PLANNING", "SELL", "RENT"]);
const BUSINESS_VERTICALS = new Set(["BUSINESS", "GRANT", "TRADE"]);

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
  const latest = project.latest_assessment;
  // One questionnaire per project today: the most recently saved answers.
  const answers = [...project.submissions].sort((a, b) =>
    b.updated_at.localeCompare(a.updated_at),
  )[0];
  // Whether the latest result is of the answers as they are now.
  const assessed = Boolean(
    latest && answers && latest.submission_id === answers.id && answers.status === "SUBMITTED",
  );
  const questionsHref = `/projects/${project.id}/questionnaire`;
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

      {props.whatsLeft && !["COMPLETED", "ARCHIVED"].includes(project.status) ? (
        <WhatsLeft left={props.whatsLeft} />
      ) : null}

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

      {BUSINESS_VERTICALS.has(project.vertical) && props.businesses ? (
        <BusinessPanel
          organisationId={organisationId}
          project={project}
          businesses={props.businesses}
          canWrite={canWrite}
          onProjectChange={setProject}
        />
      ) : null}

      {project.vertical === "VESSEL" && props.vessels ? (
        <VesselPanel
          organisationId={organisationId}
          project={project}
          vessels={props.vessels}
          canWrite={canWrite}
          onProjectChange={setProject}
        />
      ) : null}

      <section className="panel" aria-labelledby="questions-title">
        <h2 id="questions-title" className="section-title">
          Your assessment
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
            Answer a few questions about your situation and your result appears straight
            underneath: the approvals you need, how sure we are and how to apply.
          </p>
        )}
        {answers ? (
          <p className="muted">
            {SUBMISSION_LABELS[answers.status] ?? answers.status} · Last saved{" "}
            {formatDateTime(answers.updated_at)}
            {latest && !assessed ? " · changed since the last result" : ""}
          </p>
        ) : null}
        {!answers ? (
          canWrite ? (
            <button type="button" className="button" disabled={busy} onClick={startQuestionnaire}>
              Answer the questions
            </button>
          ) : (
            <p>No answers yet.</p>
          )
        ) : canWrite && answers.status !== "SUBMITTED" ? (
          <Link className="button" href={questionsHref}>
            {latest ? "Finish and update my result" : "Continue answering"}
          </Link>
        ) : (
          <Link className={canWrite ? "button" : "button button-secondary"} href={questionsHref}>
            {assessed || !canWrite ? "See answers and result" : "See my result"}
          </Link>
        )}
      </section>

      {latest && props.plan ? <PlanPanel projectId={project.id} plan={props.plan} /> : null}

      {props.council ? <CouncilGuide council={props.council} /> : null}

      {project.vertical === "SELL" ? (
        <section className="panel" aria-labelledby="sale-panel-title">
          <h2 id="sale-panel-title" className="section-title">
            Your sale
          </h2>
          <p className="muted">
            Track the sale from preparing to settlement: the document vault, disclosure to
            buyers, offers and enquiries.
          </p>
          <Link className="button button-secondary" href={`/projects/${project.id}/sale`}>
            Open the sale
          </Link>
        </section>
      ) : null}

      {project.vertical === "RENT" ? (
        <section className="panel" aria-labelledby="rental-panel-title">
          <h2 id="rental-panel-title" className="section-title">
            Your rental
          </h2>
          <p className="muted">
            The listing, applications, tenancies, inspections on your phone, and repairs, with
            reminders for bonds, lease ends and rent reviews.
          </p>
          <Link className="button button-secondary" href={`/projects/${project.id}/rental`}>
            Open the rental
          </Link>
        </section>
      ) : null}

      {project.vertical === "VESSEL" ? (
        <section className="panel" aria-labelledby="sms-panel-title">
          <h2 id="sms-panel-title" className="section-title">
            Safety management system
          </h2>
          <p className="muted">
            Every domestic commercial vessel needs a safety management system. Write yours part
            by part under the headings in Marine Order 504.
          </p>
          <Link className="button button-secondary" href={`/projects/${project.id}/sms`}>
            Open the SMS builder
          </Link>
        </section>
      ) : null}

      {props.checklists &&
      (props.checklists.length > 0 || (props.checklistDefinitions ?? []).length > 0) ? (
        <ChecklistsPanel
          organisationId={organisationId}
          projectId={project.id}
          checklists={props.checklists}
          definitions={props.checklistDefinitions ?? []}
          canWrite={canWrite}
        />
      ) : null}

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
          <form
            method="post"
            className="form inline-form"
            onSubmit={addTask}
            aria-label="Add a task"
          >
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
        <p className="muted">
          Reminders arrive in your <Link href="/notifications">notifications</Link> and by email
          at the time you choose. Dates in a sale or rental add their own reminders.
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
              {reminder.source_key ? <span className="badge">Automatic</span> : null}
              {canWrite && !reminder.source_key ? (
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
          <form
            method="post"
            className="form inline-form"
            onSubmit={addReminder}
            aria-label="Add a reminder"
          >
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

/** The project plan: its progress when there is one, or what it offers. */
function PlanPanel({ projectId, plan }: { projectId: string; plan: ProjectPlanOut }) {
  const href = `/projects/${projectId}/plan`;
  return (
    <section className="panel" aria-labelledby="plan-panel-title">
      <h2 id="plan-panel-title" className="section-title">
        Project plan
      </h2>
      {plan.status === "ACTIVE" && plan.progress ? (
        <>
          <p>
            <strong>
              {plan.progress.done} of {plan.progress.total} steps done
            </strong>
            {plan.progress.overdue ? (
              <>
                {" "}
                <span className="status status-failed">{plan.progress.overdue} overdue</span>
              </>
            ) : null}
            {plan.progress.finish_on ? (
              <span className="muted"> · finish by {formatDate(plan.progress.finish_on)}</span>
            ) : null}
          </p>
          <Link className="button" href={href}>
            Open your project plan
          </Link>
        </>
      ) : plan.status === "PAYMENT_PENDING" ? (
        <>
          <p className="muted">Your project plan is waiting for payment.</p>
          <Link className="button" href={href}>
            Finish starting your plan
          </Link>
        </>
      ) : (
        <>
          <p className="muted">
            Manage this project online: every step from your checklist on a timeline with due
            dates, owners and your files, follow-up reminders, and checked partners in your area
            to call for each part.
          </p>
          <Link className="button button-secondary" href={href}>
            See the project plan
          </Link>
        </>
      )}
    </section>
  );
}
