"""AI drafting (Milestone 12): prompt versions, AI jobs and the provider call log.

* ``prompt_version``: platform data. Reviewed prompt files are published by the migrate step
  (``python -m app.cli ai sync-prompts``); read-only for the application role, and a stored
  version is immutable (trigger), so nothing at run time can change what the model is told.
* ``ai_job``: tenant. One request for a draft and its validated output.
* ``ai_provider_log``: tenant, append-only. Every provider call: model, tokens, cost,
  latency and outcome, without prompt or output text.
* ``pending_ai_jobs()``: SECURITY DEFINER, ids of stalled jobs for the scheduler's sweep.
* ``ai_usage_summary()``: SECURITY DEFINER, call counts, tokens and cost per provider, model,
  task and outcome across all organisations, for staff. Totals only, no tenant rows.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "approvalready_rw"

# Privileges of the application role on the new tables (tests/test_rls.py keeps the map).
PRIVILEGES: dict[str, str] = {
    "prompt_version": "SELECT",
    "ai_job": "SELECT, INSERT, UPDATE",
    "ai_provider_log": "SELECT, INSERT",
}

TENANT_TABLES = ("ai_job", "ai_provider_log")

TENANT_PREDICATE = "organisation_id = nullif(current_setting('app.current_org', true), '')::uuid"

PROMPT_VERSION_GUARD = """
CREATE FUNCTION prompt_version_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'prompt versions cannot be deleted';
    END IF;
    IF NEW.task IS DISTINCT FROM OLD.task
        OR NEW.version IS DISTINCT FROM OLD.version
        OR NEW.system_prompt IS DISTINCT FROM OLD.system_prompt
        OR NEW.user_template IS DISTINCT FROM OLD.user_template
        OR NEW.output_schema_name IS DISTINCT FROM OLD.output_schema_name
        OR NEW.output_schema_version IS DISTINCT FROM OLD.output_schema_version
        OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
        OR NEW.published_at IS DISTINCT FROM OLD.published_at THEN
        RAISE EXCEPTION 'prompt versions are immutable';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status
        AND NOT (OLD.status = 'PUBLISHED' AND NEW.status = 'RETIRED') THEN
        RAISE EXCEPTION 'a prompt version can only go from PUBLISHED to RETIRED';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER prompt_version_immutable
    BEFORE UPDATE OR DELETE ON prompt_version
    FOR EACH ROW EXECUTE FUNCTION prompt_version_guard();
"""

PENDING_FUNCTION = """
CREATE FUNCTION pending_ai_jobs(older_than interval)
RETURNS TABLE (id uuid, organisation_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT j.id, j.organisation_id FROM ai_job j
     WHERE j.status = 'PENDING' AND j.updated_at < now() - older_than
     LIMIT 500
$$;
REVOKE ALL ON FUNCTION pending_ai_jobs(interval) FROM PUBLIC;
"""

USAGE_FUNCTION = """
CREATE FUNCTION ai_usage_summary(since timestamptz)
RETURNS TABLE (
    provider text, model text, task text, status text,
    calls bigint, request_tokens bigint, response_tokens bigint, cost_micros bigint
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT l.provider, l.model, l.task, l.status, count(*),
           coalesce(sum(l.request_tokens), 0), coalesce(sum(l.response_tokens), 0),
           coalesce(sum(l.cost_micros), 0)
      FROM ai_provider_log l
     WHERE l.created_at >= since
     GROUP BY l.provider, l.model, l.task, l.status
     ORDER BY l.provider, l.model, l.task, l.status
$$;
REVOKE ALL ON FUNCTION ai_usage_summary(timestamptz) FROM PUBLIC;
"""

TASKS = "task IN ('ASSESSMENT_EXPLANATION', 'GRANT_DRAFT')"


def _timestamps() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "prompt_version",
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("user_template", sa.Text(), nullable=False),
        sa.Column("output_schema_name", sa.String(length=60), nullable=False),
        sa.Column("output_schema_version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.LargeBinary(), nullable=False),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "octet_length(content_hash) = 32", name=op.f("ck_prompt_version_content_hash_sha256")
        ),
        sa.CheckConstraint(
            "status IN ('PUBLISHED', 'RETIRED')", name=op.f("ck_prompt_version_status_valid")
        ),
        sa.CheckConstraint(TASKS, name=op.f("ck_prompt_version_task_valid")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prompt_version")),
        sa.UniqueConstraint("task", "version", name=op.f("uq_prompt_version_task_version")),
    )
    op.create_index(
        "uq_prompt_version_one_published",
        "prompt_version",
        ["task"],
        unique=True,
        postgresql_where=sa.text("status = 'PUBLISHED'"),
    )
    op.create_table(
        "ai_job",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("assessment_id", sa.UUID(), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=True),
        sa.Column("prompt_version_id", sa.UUID(), nullable=False),
        sa.Column("input_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_hash", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.Text(), server_default="PENDING", nullable=False),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("validation_errors", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        *_timestamps(),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "octet_length(input_hash) = 32", name=op.f("ck_ai_job_input_hash_sha256")
        ),
        sa.CheckConstraint(
            "status <> 'SUCCEEDED' OR output IS NOT NULL",
            name=op.f("ck_ai_job_succeeded_has_output"),
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'SUCCEEDED', 'REJECTED', 'FAILED')",
            name=op.f("ck_ai_job_status_valid"),
        ),
        sa.CheckConstraint(TASKS, name=op.f("ck_ai_job_task_valid")),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_ai_job_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "assessment_id"],
            ["assessment.organisation_id", "assessment.id"],
            name=op.f("fk_ai_job_organisation_id_assessment"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "project_id"],
            ["project.organisation_id", "project.id"],
            name=op.f("fk_ai_job_organisation_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_ai_job_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_version_id"],
            ["prompt_version.id"],
            name=op.f("fk_ai_job_prompt_version_id_prompt_version"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_job")),
        sa.UniqueConstraint("organisation_id", "id", name=op.f("uq_ai_job_organisation_id_id")),
    )
    op.create_index(
        "ix_ai_job_assessment_id", "ai_job", ["assessment_id", "created_at"], unique=False
    )
    op.create_index(op.f("ix_ai_job_organisation_id"), "ai_job", ["organisation_id"], unique=False)
    op.create_table(
        "ai_provider_log",
        sa.Column("ai_job_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("prompt_version_id", sa.UUID(), nullable=False),
        sa.Column("schema_name", sa.String(length=60), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("request_tokens", sa.Integer(), nullable=True),
        sa.Column("response_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_micros", sa.BigInteger(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "status IN ('OK', 'ERROR', 'REFUSED')", name=op.f("ck_ai_provider_log_status_valid")
        ),
        sa.CheckConstraint(TASKS, name=op.f("ck_ai_provider_log_task_valid")),
        sa.ForeignKeyConstraint(
            ["organisation_id", "ai_job_id"],
            ["ai_job.organisation_id", "ai_job.id"],
            name=op.f("fk_ai_provider_log_organisation_id_ai_job"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_ai_provider_log_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_version_id"],
            ["prompt_version.id"],
            name=op.f("fk_ai_provider_log_prompt_version_id_prompt_version"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_provider_log")),
    )
    op.create_index("ix_ai_provider_log_ai_job_id", "ai_provider_log", ["ai_job_id"], unique=False)
    op.create_index(
        "ix_ai_provider_log_created_at", "ai_provider_log", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_ai_provider_log_organisation_id"),
        "ai_provider_log",
        ["organisation_id"],
        unique=False,
    )
    op.execute(PROMPT_VERSION_GUARD)
    op.execute(PENDING_FUNCTION)
    op.execute(USAGE_FUNCTION)
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
        )
    for table, privileges in PRIVILEGES.items():
        op.execute(f"GRANT {privileges} ON {table} TO {APP_ROLE}")
    op.execute(f"GRANT EXECUTE ON FUNCTION pending_ai_jobs(interval) TO {APP_ROLE}")
    op.execute(f"GRANT EXECUTE ON FUNCTION ai_usage_summary(timestamptz) TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION ai_usage_summary(timestamptz)")
    op.execute("DROP FUNCTION pending_ai_jobs(interval)")
    op.drop_index(op.f("ix_ai_provider_log_organisation_id"), table_name="ai_provider_log")
    op.drop_index("ix_ai_provider_log_created_at", table_name="ai_provider_log")
    op.drop_index("ix_ai_provider_log_ai_job_id", table_name="ai_provider_log")
    op.drop_table("ai_provider_log")
    op.drop_index(op.f("ix_ai_job_organisation_id"), table_name="ai_job")
    op.drop_index("ix_ai_job_assessment_id", table_name="ai_job")
    op.drop_table("ai_job")
    op.execute("DROP TRIGGER prompt_version_immutable ON prompt_version")
    op.execute("DROP FUNCTION prompt_version_guard()")
    op.drop_index("uq_prompt_version_one_published", table_name="prompt_version")
    op.drop_table("prompt_version")
