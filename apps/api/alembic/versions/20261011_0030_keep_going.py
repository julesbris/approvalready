"""Keep going: nudges for projects that went quiet with things still to do.

* ``notification.kind`` gains ``KEEP_GOING`` and ``notification_preference.category`` gains
  ``PROGRESS``, so people can turn these nudges off on their own.
* ``ix_notification_keep_going``: counting the nudges a project has had.
* ``quiet_projects(active_before, active_after, max_rows)``: SECURITY DEFINER, like
  ``due_reminders``. Projects still open whose last activity (the project, its answers,
  assessments, tasks, checklists, uploads and evidence) falls in the window, with the stage
  they stopped at and counts only: no titles, answers or file names. The nudge job and the
  staff "Stuck projects" page use it; everything else is read with the tenant bound.

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "approvalready_rw"

KINDS_OLD = (
    "REMINDER",
    "GRANT_ROUND",
    "SOURCES_DUE",
    "LEAD_OFFERED",
    "LEAD_CLAIMED",
    "OPS_ALERT",
    "QUOTE_RECEIVED",
    "QUOTE_ANSWERED",
    "MESSAGE_RECEIVED",
)
KINDS_NEW = (*KINDS_OLD, "KEEP_GOING")
CATEGORIES_OLD = ("REMINDERS", "GRANT_ROUNDS", "REFERRALS", "SOURCE_REVIEWS")
CATEGORIES_NEW = (*CATEGORIES_OLD, "PROGRESS")

QUIET_PROJECTS = """
CREATE FUNCTION quiet_projects(
    active_before timestamptz, active_after timestamptz, max_rows integer
)
RETURNS TABLE (
    organisation_id uuid,
    project_id uuid,
    reference_code text,
    vertical text,
    status text,
    owner_user_id uuid,
    last_activity_at timestamptz,
    stage text,
    open_tasks integer,
    documents_missing integer,
    checklist_open integer,
    nudges_sent integer,
    last_nudged_at timestamptz
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    WITH active AS (
        SELECT p.id, p.organisation_id, p.reference_code, p.vertical, p.status, p.created_by,
               greatest(
                   p.updated_at,
                   (SELECT max(s.updated_at) FROM questionnaire_submission s
                     WHERE s.project_id = p.id),
                   (SELECT max(a.created_at) FROM assessment a WHERE a.project_id = p.id),
                   (SELECT max(t.updated_at) FROM task t WHERE t.project_id = p.id),
                   (SELECT max(greatest(c.updated_at, ci.updated_at))
                      FROM project_checklist c
                      LEFT JOIN checklist_item ci ON ci.checklist_id = c.id
                     WHERE c.project_id = p.id),
                   (SELECT max(d.updated_at) FROM uploaded_document d
                     WHERE d.project_id = p.id),
                   (SELECT max(e.updated_at) FROM evidence e WHERE e.project_id = p.id)
               ) AS last_activity_at
          FROM project p
          JOIN organisation o ON o.id = p.organisation_id
         WHERE p.deleted_at IS NULL AND o.deleted_at IS NULL
           AND p.status IN ('DRAFT', 'IN_PROGRESS', 'ASSESSED')
    ),
    staged AS (
        SELECT q.*, tasks.n AS open_tasks, docs.n AS documents_missing,
               checks.n AS checklist_open,
               CASE
                   WHEN sub.id IS NULL THEN 'START'
                   WHEN sub.status = 'IN_PROGRESS' THEN 'QUESTIONS'
                   WHEN asm.id IS NULL OR asm.submission_id <> sub.id THEN 'RESULTS'
                   WHEN docs.n > 0 THEN 'DOCUMENTS'
                   WHEN tasks.n > 0 OR checks.n > 0 THEN 'TASKS'
               END AS stage
          FROM active q
          LEFT JOIN LATERAL (
                SELECT s.id, s.status FROM questionnaire_submission s
                 WHERE s.project_id = q.id ORDER BY s.updated_at DESC LIMIT 1
               ) sub ON true
          LEFT JOIN LATERAL (
                SELECT a.id, a.submission_id FROM assessment a
                 WHERE a.project_id = q.id ORDER BY a.created_at DESC LIMIT 1
               ) asm ON true
          CROSS JOIN LATERAL (
                SELECT count(*)::integer AS n FROM task t
                 WHERE t.project_id = q.id AND t.deleted_at IS NULL AND t.status = 'OPEN'
               ) tasks
          CROSS JOIN LATERAL (
                SELECT count(*)::integer AS n FROM evidence_requirement r
                 WHERE r.assessment_id = asm.id
                   AND NOT EXISTS (
                       SELECT 1 FROM evidence e
                        WHERE e.evidence_requirement_id = r.id AND e.status <> 'REJECTED'
                   )
               ) docs
          CROSS JOIN LATERAL (
                SELECT count(*)::integer AS n
                  FROM checklist_item ci JOIN project_checklist c ON c.id = ci.checklist_id
                 WHERE c.project_id = q.id AND ci.required AND ci.status = 'OPEN'
               ) checks
         WHERE q.last_activity_at < active_before AND q.last_activity_at >= active_after
    )
    SELECT st.organisation_id, st.id, st.reference_code::text, st.vertical, st.status,
           st.created_by, st.last_activity_at, st.stage, st.open_tasks,
           st.documents_missing, st.checklist_open, nudges.sent, nudges.last_at
      FROM staged st
     CROSS JOIN LATERAL (
           SELECT count(*)::integer AS sent, max(x.created_at) AS last_at FROM notification x
            WHERE x.project_id = st.id AND x.kind = 'KEEP_GOING'
              AND x.created_at > st.last_activity_at
          ) nudges
     WHERE st.stage IS NOT NULL
     ORDER BY st.last_activity_at DESC, st.id
     LIMIT least(greatest(max_rows, 1), 5000)
$$;
REVOKE ALL ON FUNCTION quiet_projects(timestamptz, timestamptz, integer) FROM PUBLIC;
"""


def _check(table: str, column: str, values: tuple[str, ...]) -> None:
    name = op.f(f"ck_{table}_{column}_valid")
    op.drop_constraint(name, table)
    quoted = ", ".join(f"'{v}'" for v in values)
    op.create_check_constraint(name, table, f"{column} IN ({quoted})")


def upgrade() -> None:
    _check("notification", "kind", KINDS_NEW)
    _check("notification_preference", "category", CATEGORIES_NEW)
    op.create_index(
        "ix_notification_keep_going",
        "notification",
        ["project_id", "created_at"],
        unique=False,
        postgresql_where=sa.text("kind = 'KEEP_GOING'"),
    )
    op.execute(QUIET_PROJECTS)
    op.execute(
        f"GRANT EXECUTE ON FUNCTION quiet_projects(timestamptz, timestamptz, integer) TO {APP_ROLE}"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION quiet_projects(timestamptz, timestamptz, integer)")
    op.drop_index("ix_notification_keep_going", table_name="notification")
    op.execute("DELETE FROM notification_preference WHERE category = 'PROGRESS'")
    op.execute("DELETE FROM notification WHERE kind = 'KEEP_GOING'")
    _check("notification_preference", "category", CATEGORIES_OLD)
    _check("notification", "kind", KINDS_OLD)
