"""TradeReady (Milestone 25): a seventh product vertical, ``TRADE``, for businesses importing
goods into or exporting goods out of Australia.

Only the check constraints that list the verticals change. A downgrade puts the old lists
back as ``NOT VALID`` constraints, so rows already using ``TRADE`` (synced categories, the
review product, the trade questionnaire) don't block it; new rows are still checked.

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = ("PLANNING", "VESSEL", "BUSINESS", "GRANT", "SELL", "RENT")
NEW = (*OLD, "TRADE")

# (table, constraint name, nullable column)
VERTICAL_CHECKS = (
    ("project", "ck_project_vertical_valid", False),
    ("questionnaire", "ck_questionnaire_vertical_valid", False),
    ("rule_set", "ck_rule_set_vertical_valid", False),
    ("professional_service", "ck_professional_service_vertical_valid", False),
    ("product", "ck_product_vertical_valid", True),
)


def _in_list(verticals: tuple[str, ...], *, nullable: bool) -> str:
    sql = "vertical IN ({})".format(", ".join(f"'{v}'" for v in verticals))
    return f"vertical IS NULL OR {sql}" if nullable else sql


def _array(verticals: tuple[str, ...]) -> str:
    return "verticals <@ ARRAY[{}]::text[] AND cardinality(verticals) > 0".format(
        ",".join(f"'{v}'" for v in verticals)
    )


def _replace(verticals: tuple[str, ...], *, validate: bool) -> None:
    checks = [(t, n, _in_list(verticals, nullable=nullable)) for t, n, nullable in VERTICAL_CHECKS]
    checks.append(
        (
            "marketplace_category",
            "ck_marketplace_category_verticals_valid",
            _array(verticals),
        )
    )
    for table, name, sql in checks:
        op.drop_constraint(op.f(name), table, type_="check")
        suffix = "" if validate else " NOT VALID"
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({sql}){suffix}")


def upgrade() -> None:
    _replace(NEW, validate=True)


def downgrade() -> None:
    _replace(OLD, validate=False)
